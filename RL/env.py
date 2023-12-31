import numpy as np
import os
from sklearn.model_selection import train_test_split
import gym
import torch
import RL.utils as utils
from RL.guesser import Guesser


class myEnv(gym.Env):

    def __init__(self,
                 flags,
                 device,
                 oversample=True,
                 load_pretrained_guesser=True):
        self.guesser = Guesser()
        episode_length = flags.episode_length
        self.device = device
        self.X_train, self.X_test, self.y_train, self.y_test = train_test_split(self.guesser.X, self.guesser.y,
                                                                                test_size=0.3)
        self.X_train, self.X_val, self.y_train, self.y_val = train_test_split(self.X_train,
                                                                              self.y_train,
                                                                              test_size=0.05)
        self.episode_length = episode_length
        self.action_probs = utils.prob_actions()
        # Load pre-trained guesser network, if needed
        if load_pretrained_guesser:
            save_dir = os.path.join(os.getcwd(), 'model_guesser')
            guesser_filename = 'best_guesser.pth'
            guesser_load_path = os.path.join(save_dir, guesser_filename)
            if os.path.exists(guesser_load_path):
                print('Loading pre-trained guesser')
                guesser_state_dict = torch.load(guesser_load_path)
                self.guesser.load_state_dict(guesser_state_dict)

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

        self.state = np.concatenate([np.zeros(self.guesser.features_size), np.zeros(self.guesser.features_size)])

        if mode == 'training':
            self.patient = np.random.randint(self.X_train.shape[0])
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
        mask = torch.ones(self.guesser.features_size+1)
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

        if action < self.guesser.features_size:  # Not making a guess
            if mode == 'training':
                next_state[action] = self.X_train[self.patient, action]
            elif mode == 'val':
                next_state[action] = self.X_val[self.patient, action]
            elif mode == 'test':
                next_state[action] = self.X_test[self.patient, action]
            next_state[action + self.guesser.features_size] += 1.
            self.guess = -1
            self.done = False

        else:  # Making a guess
            guesser_input = torch.Tensor(
                self.state[:self.guesser.features_size])
            if torch.cuda.is_available():
                guesser_input = guesser_input.cuda()
            self.guesser.train(mode=False)
            self.probs = self.guesser(guesser_input)
            self.guess = torch.argmax(self.probs).item()
            self.correct_prob = self.probs[self.y_train[self.patient]].item()
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
            self.guesser.loss = self.guesser.criterion(self.probs, y)
            self.guesser.loss.backward()
            self.guesser.optimizer.step()
            # update learning rate
            self.guesser.update_learning_rate()

        return reward
