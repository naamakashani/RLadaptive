import torch.nn
from collections import deque
from typing import List, Tuple
from sklearn.metrics import confusion_matrix
from env import *
from agent import *
from ReplayMemory import *
from itertools import count

parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
parser.add_argument("--save_dir",
                    type=str,
                    default='ddqn_models',
                    help="Directory for saved models")
parser.add_argument("--directory",
                    type=str,
                    default="C:\\Users\\kashann\\PycharmProjects\\choiceMira\\RL",
                    help="Directory for saved models")

parser.add_argument("--gamma",
                    type=float,
                    default=0.85,
                    help="Discount rate for Q_target")
parser.add_argument("--n_update_target_dqn",
                    type=int,
                    default=10,
                    help="Number of episodes between updates of target dqn")
parser.add_argument("--val_trials_wo_im",
                    type=int,
                    default=100,
                    help="Number of validation trials without improvement")
parser.add_argument("--ep_per_trainee",
                    type=int,
                    default=1000,
                    help="Switch between training dqn and guesser every this # of episodes")
parser.add_argument("--batch_size",
                    type=int,
                    default=64,
                    help="Mini-batch size")
parser.add_argument("--hidden-dim",
                    type=int,
                    default=64,
                    help="Hidden dimension")
parser.add_argument("--capacity",
                    type=int,
                    default=10000,
                    help="Replay memory capacity")
parser.add_argument("--max-episode",
                    type=int,
                    default=2000,
                    help="e-Greedy target episode (eps will be the lowest at this episode)")
parser.add_argument("--min-eps",
                    type=float,
                    default=0.01,
                    help="Min epsilon")
parser.add_argument("--lr",
                    type=float,
                    default=1e-4,
                    help="Learning rate")
parser.add_argument("--weight_decay",
                    type=float,
                    default=0e-4,
                    help="l_2 weight penalty")
parser.add_argument("--val_interval",
                    type=int,
                    default=1000,
                    help="Interval for calculating validation reward and saving model")
parser.add_argument("--episode_length",
                    type=int,
                    default=7,
                    help="Episode length")
parser.add_argument("--case",
                    type=int,
                    default=2,
                    help="Which data to use")
parser.add_argument("--env",
                    type=str,
                    default="Questionnaire",
                    help="environment name: Questionnaire")
# Environment params
parser.add_argument("--g_hidden-dim",
                    type=int,
                    default=256,
                    help="Guesser hidden dimension")
parser.add_argument("--g_weight_decay",
                    type=float,
                    default=0e-4,
                    help="Guesser l_2 weight penalty")

FLAGS = parser.parse_args(args=[])

# set device
device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")


def train_helper(agent: Agent,
                 minibatch: List[Transition],
                 gamma: float) -> float:
    """Prepare minibatch and train them
    Args:
        agent (Agent): Agent has `train(Q_pred, Q_true)` method
        minibatch (List[Transition]): Minibatch of `Transition`
        gamma (float): Discount rate of Q_target
    Returns:
        float: Loss value
    """
    states = np.vstack([x.state for x in minibatch])
    actions = np.array([x.action for x in minibatch])
    rewards = np.array([x.reward for x in minibatch])
    next_states = np.vstack([x.next_state for x in minibatch])
    done = np.array([x.done for x in minibatch])

    Q_predict = agent.get_Q(states)
    Q_target = Q_predict.clone().cpu().data.numpy()
    max_actions = np.argmax(agent.get_Q(next_states).cpu().data.numpy(), axis=1)
    Q_target[np.arange(len(Q_target)), actions] = rewards + gamma * agent.get_target_Q(next_states)[
        np.arange(len(Q_target)), max_actions].data.numpy() * ~done
    Q_target = agent._to_variable(Q_target).to(device=device)

    return agent.train(Q_predict, Q_target)


def play_episode(env,
                 agent: Agent,
                 replay_memory: ReplayMemory,
                 eps: float,
                 batch_size: int,
                 train_guesser=True,
                 train_dqn=True, mode='training') -> int:
    """Play an epsiode and train
    Args:
        env (gym.Env): gym environment (CartPole-v0)
        agent (Agent): agent will train and get action
        replay_memory (ReplayMemory): trajectory is saved here
        eps (float): 𝜺-greedy for exploration
        batch_size (int): batch size
    Returns:
        int: reward earned in this episode
    """
    s = env.reset(train_guesser=train_guesser)
    done = False
    total_reward = 0
    mask = env.reset_mask()

    t = 0
    while not done:
        a = agent.get_action(s, env, eps, mask, mode)
        s2, r, done, info = env.step(a, mask)
        mask[a] = 0
        total_reward += r
        replay_memory.push(s, a, r, s2, done)
        if len(replay_memory) > batch_size:
            if train_dqn:
                minibatch = replay_memory.pop(batch_size)
                train_helper(agent, minibatch, FLAGS.gamma)

        s = s2
        t += 1
        # check
        if t == FLAGS.episode_length:
            # a = agent.output_dim - 1
            # s2, r, done, info = env.step(a, mask)
            # mask[a] = 0
            # total_reward += r
            # replay_memory.push(s, a, r, s2, done)
            # t += 1
            break

    if train_dqn:
        agent.update_learning_rate()

    return total_reward, t


def get_env_dim(env) -> Tuple[int, int]:
    """Returns input_dim & output_dim
    Args:
        env (gym.Env): gym Environment
    Returns:
        int: input_dim
        int: output_dim
    """
    input_dim = 2 * env.guesser.features_size
    output_dim = env.guesser.features_size + 1

    return input_dim, output_dim


def epsilon_annealing(episode: int, max_episode: int, min_eps: float) -> float:
    """Returns 𝜺-greedy
    1.0---|\
          | \
          |  \
    min_e +---+------->
              |
              max_episode
    Args:
        epsiode (int): Current episode (0<= episode)
        max_episode (int): After max episode, 𝜺 will be `min_eps`
        min_eps (float): 𝜺 will never go below this value
    Returns:
        float: 𝜺 value
    """

    slope = (min_eps - 1.0) / max_episode
    return max(slope * episode + 1.0, min_eps)


def save_networks(i_episode: int, env, agent,
                  val_acc=None) -> None:
    """ A method to save parameters of guesser and dqn """
    if not os.path.exists(FLAGS.save_dir):
        os.makedirs(FLAGS.save_dir)

    if i_episode == 'best':
        guesser_filename = 'best_guesser.pth'
        dqn_filename = 'best_dqn.pth'
    else:
        guesser_filename = '{}_{}_{:1.3f}.pth'.format(i_episode, 'guesser', val_acc)
        dqn_filename = '{}_{}_{:1.3f}.pth'.format(i_episode, 'dqn', val_acc)

    guesser_save_path = os.path.join(FLAGS.save_dir, guesser_filename)
    dqn_save_path = os.path.join(FLAGS.save_dir, dqn_filename)

    # save guesser
    if os.path.exists(guesser_save_path):
        os.remove(guesser_save_path)
    torch.save(env.guesser.cpu().state_dict(), guesser_save_path + '~')
    env.guesser.to(device=device)
    os.rename(guesser_save_path + '~', guesser_save_path)

    # save dqn
    if os.path.exists(dqn_save_path):
        os.remove(dqn_save_path)
    torch.save(agent.dqn.cpu().state_dict(), dqn_save_path + '~')
    agent.dqn.to(device=device)
    os.rename(dqn_save_path + '~', dqn_save_path)


# Function to extract states from replay memory
def extract_states_from_replay_memory(replay_memory):
    states = []
    for experience in replay_memory:
        state = experience['state']  # Assuming 'state' key holds the state information
        states.append(state)
    return np.array(states)


def load_networks(i_episode: int, env, input_dim=26, output_dim=14,
                  val_acc=None) -> None:
    """ A method to load parameters of guesser and dqn """
    if i_episode == 'best':
        guesser_filename = 'best_guesser.pth'
        dqn_filename = 'best_dqn.pth'
    else:
        guesser_filename = '{}_{}_{:1.3f}.pth'.format(i_episode, 'guesser', val_acc)
        dqn_filename = '{}_{}_{:1.3f}.pth'.format(i_episode, 'dqn', val_acc)

    guesser_load_path = os.path.join(FLAGS.save_dir, guesser_filename)
    dqn_load_path = os.path.join(FLAGS.save_dir, dqn_filename)

    # load guesser
    guesser = Guesser()
    guesser_state_dict = torch.load(guesser_load_path)
    guesser.load_state_dict(guesser_state_dict)
    guesser.to(device=device)

    # load sqn
    dqn = DQN(input_dim, output_dim, FLAGS.hidden_dim)
    dqn_state_dict = torch.load(dqn_load_path)
    dqn.load_state_dict(dqn_state_dict)
    dqn.to(device=device)

    return guesser, dqn


def main():
    # define environment and agent (needed for main and test)
    env = myEnv(flags=FLAGS,
                device=device)
    clear_threshold = 1.
    input_dim, output_dim = get_env_dim(env)
    agent = Agent(input_dim,
                  output_dim,
                  FLAGS.hidden_dim, FLAGS.lr, FLAGS.weight_decay)

    agent.dqn.to(device=device)
    env.guesser.to(device=device)

    # store best result
    best_val_acc = 0

    # counter of validation trials with no improvement, to determine when to stop training
    val_trials_without_improvement = 0

    # set up trainees for first cycle
    train_guesser = False
    train_dqn = True

    rewards = deque(maxlen=100)
    steps = deque(maxlen=100)

    replay_memory = ReplayMemory(FLAGS.capacity)


    for i in count(1):
        train_dqn = True
        train_guesser = False

        # set exploration epsilon
        eps = epsilon_annealing(i, FLAGS.max_episode, FLAGS.min_eps)

        # play an episode
        r, t = play_episode(env,
                            agent,
                            replay_memory,
                            eps,
                            FLAGS.batch_size,
                            train_dqn=train_dqn,
                            train_guesser=train_guesser, mode='training')

        rewards.append(r)
        steps.append(t)
        if i % FLAGS.val_interval == 0:
            # compute performance on validation set
            new_best_val_acc = val(i_episode=i,
                                   best_val_acc=best_val_acc, env=env, agent=agent)

            # update best result on validation set and counter
            if new_best_val_acc > best_val_acc:
                best_val_acc = new_best_val_acc
                val_trials_without_improvement = 0
            else:
                val_trials_without_improvement += 1

        if val_trials_without_improvement >= int(FLAGS.val_trials_wo_im / 2):
            break

        if i % FLAGS.n_update_target_dqn == 0:
            agent.update_target_dqn()

    test(env, agent, input_dim, output_dim)

    show_sample_paths(6, env, agent)



def val(i_episode: int,
        best_val_acc: float, env, agent) -> float:
    """ Compute performance on validation set and save current models """

    print('Running validation')
    y_hat_val = np.zeros(len(env.y_val))

    for i in range(len(env.X_val)):  # count(1)
        state = env.reset(mode='val',
                          patient=i,
                          train_guesser=False)
        mask = env.reset_mask()

        # run episode
        for t in range(FLAGS.episode_length):

            # select action from policy
            action = agent.get_action(state, env, eps=0, mask=mask, mode='val')
            mask[action] = 0

            # take the action
            state, reward, done, guess = env.step(action, mask, mode='val')

            if guess != -1:
                y_hat_val[i] = guess

            if done:
                break

        if guess == -1:
            a = agent.output_dim - 1
            s2, r, done, info = env.step(a, mask)
            y_hat_val[i] = env.guess

    confmat = confusion_matrix(env.y_val, y_hat_val)
    acc = np.sum(np.diag(confmat)) / len(env.y_val)
    print('Validation accuracy: {:1.3f}'.format(acc))

    if acc > best_val_acc:
        print('New best acc acheievd, saving best model')
        save_networks(i_episode, env, agent, acc)
        save_networks(i_episode='best', env=env, agent=agent)

        return acc

    else:
        return best_val_acc


def test(env, agent, input_dim, output_dim):
    total_steps = 0
    """ Computes performance nad test data """

    print('Loading best networks')
    env.guesser, agent.dqn = load_networks(i_episode='best', env=env, input_dim=input_dim, output_dim=output_dim)
    # predict outcome on test data
    y_hat_test = np.zeros(len(env.y_test))
    # y_hat_test_prob = np.zeros(len(env.y_test))

    print('Computing predictions of test data')
    n_test = len(env.X_test)
    for i in range(n_test):
        number_of_steps = 0
        state = env.reset(mode='test',
                          patient=i,
                          train_guesser=False)
        mask = env.reset_mask()

        # run episode
        for t in range(FLAGS.episode_length):
            number_of_steps += 1
            # select action from policy
            action = agent.get_action(state, env, eps=0, mask=mask, mode='test')
            mask[action] = 0
            # take the action
            state, reward, done, guess = env.step(action, mask, mode='test')

            if guess != -1:
                y_hat_test[i] = env.guess

            if done:
                total_steps += number_of_steps
                break
        if guess == -1:
            number_of_steps += 1
            a = agent.output_dim - 1
            s2, r, done, info = env.step(a, mask)
            y_hat_test[i] = env.guess
            total_steps += number_of_steps

    C = confusion_matrix(env.y_test, y_hat_test)
    print('confusion matrix: ')
    print(C)
    acc = np.sum(np.diag(C)) / len(env.y_test)
    print('Test accuracy: ', np.round(acc, 3))
    print('Average number of steps: ', np.round(total_steps / n_test, 3))


# def generate_shap_values(agent, env, state, data):
#     # Generate SHAP values using your preferred SHAP library and model explainer
#     # For example, using KernelExplainer from the SHAP library
#     explainer = shap.KernelExplainer(agent.get_action, data)
#     shap_values = explainer.shap_values(state)
#     return shap_values


def show_sample_paths(n_patients, env, agent):
    """A method to run episodes on randomly chosen positive and negative test patients, and print trajectories to console  """

    # load best performing networks
    print('Loading best networks')
    input_dim, output_dim = get_env_dim(env)
    env.guesser, agent.dqn = load_networks(i_episode='best', env=env, input_dim=input_dim, output_dim=output_dim)

    for i in range(n_patients):
        print('Starting new episode with a new test patient')
        if i % 2 == 0:
            idx = np.random.choice(np.where(env.y_test == 1)[0])
        else:
            idx = np.random.choice(np.where(env.y_test == 0)[0])
        state = env.reset(mode='test',
                          patient=idx,
                          train_guesser=False)

        mask = env.reset_mask()

        # run episode
        for t in range(FLAGS.episode_length):

            # select action from policy
            action = agent.get_action(state, env, eps=0, mask=mask, mode='test')
            mask[action] = 0

            if action != env.guesser.features_size:
                print('Step: {}, Question: '.format(t + 1), env.guesser.question_names[action], ', Answer: ',
                      env.X_test[idx, action])

            # take the action
            state, reward, done, guess = env.step(action, mask, mode='test')

            if guess != -1:
                print('Step: {}, Ready to make a guess: Prob({})={:1.3f}, Guess: y={}, Ground truth: {}'.format(t + 1,
                                                                                                                guess,
                                                                                                                env.probs[
                                                                                                                    guess],
                                                                                                                guess,
                                                                                                                env.y_test[
                                                                                                                    idx]))

                break

        if guess == -1:
            state, reward, done, guess = env.step(14, mask, mode='test')

            print('Step: {}, Ready to make a guess: Prob({})={:1.3f}, Guess: y={}, Ground truth: {}'.format(t + 1,
                                                                                                            guess,
                                                                                                            env.probs[
                                                                                                                guess],
                                                                                                            guess,
                                                                                                            env.y_test[
                                                                                                                idx]))
        print('Episode terminated\n')


if __name__ == '__main__':
    os.chdir(FLAGS.directory)
    main()
