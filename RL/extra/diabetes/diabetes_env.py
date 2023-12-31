import numpy as np
import os
from sklearn.model_selection import train_test_split
import gym
import torch
import torch.nn as nn
from torch.optim import lr_scheduler
import torch.nn.functional as F
import RL.utils as utils


class Guesser(nn.Module):
    """
    implements a net that guesses the outcome given the state
    """

    def __init__(self,
                 state_dim,
                 hidden_dim,
                 num_classes=2,
                 lr=1e-4,
                 min_lr=1e-6,
                 weight_decay=0.,
                 decay_step_size=12500,
                 lr_decay_factor=0.1):
        super(Guesser, self).__init__()

        self.min_lr = min_lr

        self.image_size = 8
        self.fc0 = nn.Linear(self.image_size, 128)
        self.fc1 = nn.Linear(128, 64)
        self.fc2 = nn.Linear(64, 2)
        self.criterion = nn.CrossEntropyLoss()

        self.optimizer = torch.optim.Adam(self.parameters(),
                                          weight_decay=0.,
                                          lr=1e-4)

        self.lambda_rule = lambda x: np.power(lr_decay_factor, int(np.floor((x + 1) / decay_step_size)))

        self.scheduler = lr_scheduler.LambdaLR(self.optimizer,
                                               lr_lambda=self.lambda_rule)

    def forward(self, x):
        x = x.view(-1, self.image_size)
        x = F.relu(self.fc0(x))
        x = F.relu(self.fc1(x))
        logits = self.fc2(x)
        probs = F.softmax(logits, dim=1)
        return logits, probs

    def update_learning_rate(self):
        """ Learning rate updater """

        self.scheduler.step()
        lr = self.optimizer.param_groups[0]['lr']
        if lr < self.min_lr:
            self.optimizer.param_groups[0]['lr'] = self.min_lr
            lr = self.optimizer.param_groups[0]['lr']
        # print('Guesser learning rate = %.7f' % lr)

    def _to_variable(self, x: np.ndarray) -> torch.Tensor:
        """torch.Variable syntax helper
        Args:
            x (np.ndarray): 2-D tensor of shape (n, input_dim)
        Returns:
            torch.Tensor: torch variable
        """
        return torch.autograd.Variable(torch.Tensor(x))


class diabetes_env(gym.Env):
    """ Questionnaire Environment class
       Args:
           case (int): which data to use
           oversample (Boolean): whether to oversample the small class
           load_pretrained_guesser (Boolean): whether to load a pretrained guesser
       """

    def __init__(self,
                 flags,
                 device,
                 oversample=True,
                 load_pretrained_guesser=True):

        case = flags.case
        episode_length = flags.episode_length
        self.device = device

        # Load data
        self.n_questions = 8
        X, y, self.question_names = utils.load_diabetes()
        self.X_train, self.X_test, self.y_train, self.y_test = train_test_split(X,
                                                                                y,
                                                                                test_size=0.017)

        self.X_train, self.X_val, self.y_train, self.y_val = train_test_split(self.X_train,
                                                                              self.y_train,
                                                                              test_size=0.017)

        self.guesser = Guesser(state_dim=self.n_questions,
                               hidden_dim=flags.g_hidden_dim,
                               lr=flags.lr,
                               min_lr=flags.min_lr,
                               weight_decay=flags.g_weight_decay,
                               decay_step_size=12500,
                               lr_decay_factor=0.1)

        self.episode_length = episode_length
        self.action_probs = utils.diabetes_prob_actions()

        # Load pre-trained guesser network, if needed
        if load_pretrained_guesser:
            save_dir= os.path.join(os.getcwd(), 'model_guesser')
            save_dir = 'C:\\Users\\kashann\\PycharmProjects\\RLadaptive\\RL\\diabetes\\model_guesser_diabetes'
            guesser_filename = 'best_guesser.pth'
            guesser_load_path = os.path.join(save_dir, guesser_filename)
            if os.path.exists(guesser_load_path):
                print('Loading pre-trained guesser')
                guesser_state_dict = torch.load(guesser_load_path)
                self.guesser.load_state_dict(guesser_state_dict)



        print('Initialized questionnaire environment')

        # Reset environment

    def reset(self,
              mode='training',
              patient=0,
              train_guesser=True):
        """
        Args: mode: training / val / test
              patient (int): index of patient
              train_guesser (Boolean): flag indicating whether to train guesser network in this episode

        Selects a patient (random for training, or pre-defined for val and test) ,
        Resets the state to contain the basic information,
        Resets 'done' flag to false,
        Resets 'train_guesser' flag
        """

        self.state = np.concatenate([np.zeros(self.n_questions), np.zeros(self.n_questions)])

        if mode == 'training':
            self.patient = np.random.randint(self.X_train.shape[0])
            # chooe a random patient with 0 y_label
            # while self.y_train[self.patient] == 1:
            #     self.patient = np.random.randint(self.X_train.shape[0])
        else:
            self.patient = patient

        self.done = False
        self.s = np.array(self.state)
        self.time = 0
        if mode == 'training':
            self.train_guesser = train_guesser
        else:
            self.train_guesser = False
        return self.s

    def reset_mask(self):
        """ A method that resets the mask that is applied
        to the q values, so that questions that were already
        asked will not be asked again.
        """
        mask = torch.ones(self.n_questions + 1)
        mask = mask.to(device=self.device)

        return mask

    def step(self,
             action, mask,
             mode='training'):
        """ State update mechanism """

        # update state
        next_state = self.update_state(action, mode, mask)
        self.state = np.array(next_state)
        self.s = np.array(self.state)

        # compute reward
        self.reward = self.compute_reward(mode)

        self.time += 1
        if self.time == self.episode_length:
            self.terminate_episode()

        return self.s, self.reward, self.done, self.guess

    # Update 'done' flag when episode terminates
    def terminate_episode(self):
        self.done = True

    def update_state(self, action, mode, mask):
        next_state = np.array(self.state)

        if action < self.n_questions:  # Not making a guess
            if mode == 'training':
                next_state[action] = self.X_train[self.patient, action]
            elif mode == 'val':
                next_state[action] = self.X_val[self.patient, action]
            elif mode == 'test':
                next_state[action] = self.X_test[self.patient, action]
            next_state[action + self.n_questions] += 1.
            self.guess = -1
            self.done = False

        else:  # Making a guess
            # run guesser, and store guess and outcome probability
            # guesser_input = self.guesser._to_variable(self.state.reshape(-1, 2 * self.n_questions))
            # change the input od the state take the first 28*28 and mulriply by mask
            guesser_input = self.guesser._to_variable(
                self.state[:self.n_questions] * self.state[-1 * self.n_questions:])
            if torch.cuda.is_available():
                guesser_input = guesser_input.cuda()
            self.guesser.train(mode=False)
            self.logits, self.probs = self.guesser(guesser_input)
            self.guess = torch.argmax(self.probs.squeeze()).item()
            self.outcome_prob = self.probs.squeeze()[1].item()
            if mode == 'training':
                # store probability of true outcome for reward calculation
                self.correct_prob = self.probs.squeeze()[self.y_train[self.patient]].item()
            self.terminate_episode()

        return next_state

    def compute_reward(self, mode):
        """ Compute the reward """

        if mode == 'test':
            return None

        if self.guess == -1:  # no guess was made
            return .01 * np.random.rand()
        else:
            reward = self.correct_prob

        if mode == 'training':
            y_true = self.y_train[self.patient]

        if self.train_guesser:
            # train guesser
            self.guesser.optimizer.zero_grad()
            y = torch.Tensor([y_true]).long()
            y = y.to(device=self.device)
            self.guesser.train(mode=True)
            self.guesser.loss = self.guesser.criterion(self.logits, y)
            self.guesser.loss.backward()
            self.guesser.optimizer.step()
            # update learning rate
            self.guesser.update_learning_rate()

        return reward
