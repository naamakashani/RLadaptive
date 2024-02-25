import gymnasium
from agent_lstm import *
from RL.lstm_model.lstm_guesser import *
from RL.lstm_model.state import *
import torch.nn.functional as F
import torch
import torch.nn as nn
import torch.optim as optim


class myEnv(gymnasium.Env):

    def __init__(self,
                 flags,
                 device):

        self.device = device
        self.embedding_dim=10
        self.X, self.y, self.question_names, self.features_size = utils.load_data_labels()
        self.X, self.y = utils.balance_class(self.X, self.y)
        self.guesser = Guesser(self.embedding_dim*2)

        self.question_embedding = nn.Embedding(self.features_size,self.embedding_dim)
        self.state = State(self.features_size, self.embedding_dim, self.device)
        self.X_train, self.X_test, self.y_train, self.y_test = train_test_split(self.X, self.y,
                                                                                test_size=0.3)
        self.X_train, self.X_val, self.y_train, self.y_val = train_test_split(self.X_train,
                                                                              self.y_train,
                                                                              test_size=0.05)
        cost_list = np.array(np.ones(self.guesser.features_size + 1))
        self.action_probs = torch.from_numpy(np.array(cost_list))
        self.criterion = nn.CrossEntropyLoss()
        self.optimizer_guesser = optim.Adam(self.guesser.parameters(), lr=flags.lr)
        self.optimizer_state = optim.Adam(self.state.parameters(), lr=flags.lr)
        self.optimizer_embedding = optim.Adam(self.question_embedding.parameters(), lr=flags.lr)


    def reset(self,
              mode='training',
              patient=0,
              train_guesser=True):

        # Reset state
        self.state.reset_states()
        self.s = self.state.lstm_h.data.cpu().numpy()

        if mode == 'training':
            self.patient = np.random.randint(self.X_train.shape[0])
        else:
            self.patient = patient

        self.done = False
        self.s = np.array(self.s)
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
        mask = torch.ones(self.guesser.features_size + 1)
        mask = mask.to(device=self.device)
        return mask

    def step(self,
             action, mask
             , i, mode='training'):
        """ State update mechanism """

        # update state
        next_state = self.update_state(action, mode, mask, i)
        self.s = next_state

        # compute reward
        self.reward = self.compute_reward(mode)

        self.time += 1
        if self.time == self.guesser.features_size:
            self.terminate_episode()

        return self.s, self.reward, self.done, self.guess

    # Update 'done' flag when episode terminates
    def terminate_episode(self):
        self.done = True

    def prob_guesser(self, state):
        guesser_input = torch.Tensor(
            state[:self.guesser.features_size])
        if torch.cuda.is_available():
            guesser_input = guesser_input.cuda()
        self.guesser.train(mode=False)
        self.probs = self.guesser(guesser_input)
        self.probs = F.softmax(self.probs, dim=1)
        self.guess = torch.argmax(self.probs).item()
        class_index = self.y_train[self.patient].item()
        self.correct_prob = self.probs[0, class_index].item()
        return self.correct_prob

    def update_state(self, action, mode, mask, eps):
        prev_state = self.s

        if action < self.guesser.features_size:  # Not making a guess
            if mode == 'training':
                answer = self.X_train[self.patient, action]
            elif mode == 'val':
                answer = self.X_val[self.patient, action]
            elif mode == 'test':
                answer = self.X_test[self.patient, action]

            question_embedding = self.question_embedding(torch.tensor(action))
            question_embedding = question_embedding.to(device=self.device)
            next_state = self.state(question_embedding,answer)

            # answer_encode = torch.zeros(1, self.guesser.features_size).to(device=self.device)
            #
            # answer_encode[0, action] = torch.tensor(answer, dtype=torch.float32)
            # next_state = self.state(answer_encode)

            next_state = torch.autograd.Variable(torch.Tensor(next_state))
            next_state = next_state.float()
            probs = self.guesser(next_state)
            y_true = self.y_train[self.patient]
            y_tensor = torch.tensor([int(y_true)])
            y_true_tensor = F.one_hot(y_tensor, num_classes=2)
            self.probs = probs.float()
            self.probs = F.softmax(self.probs, dim=1)
            y_true_tensor = y_true_tensor.float()
            self.loss = self.criterion(self.probs, y_true_tensor)
            self.loss.backward()
            if eps >= 0:
                if np.random.rand() > eps:
                    self.optimizer_state.step()
                    self.optimizer_state.zero_grad()
                    self.optimizer_embedding.step()
                    self.optimizer_embedding.zero_grad()
                else:
                    self.optimizer_guesser.step()
                    self.optimizer_guesser.zero_grad()
            self.reward = self.prob_guesser(next_state) - self.prob_guesser(prev_state)
            self.guess = -1
            self.done = False
            return next_state

        else:
            self.reward = self.prob_guesser(prev_state)
            self.terminate_episode()
            return prev_state

    def compute_reward(self, mode):
        """ Compute the reward """

        if mode == 'test':
            return None

        if self.guess == -1:  # no guess was made
            return self.reward

        if mode == 'training':
            y_true = self.y_train[self.patient]
            if self.train_guesser:
                self.guesser.optimizer.zero_grad()
                self.guesser.train(mode=True)
                y_tensor = torch.tensor([int(y_true)])
                y_true_tensor = F.one_hot(y_tensor, num_classes=2).squeeze()
                self.probs = self.probs.float()
                y_true_tensor = y_true_tensor.float()
                self.guesser.loss = self.guesser.criterion(self.probs, y_true_tensor)
                self.guesser.loss.backward()
                self.guesser.optimizer.step()

        return self.reward
