import gymnasium
from agent_lstm import *
from RL.lstm_model.lstm_guesser import *

import torch.nn.functional as F

parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
parser.add_argument("--directory",
                    type=str,
                    default="C:\\Users\\kashann\\PycharmProjects\\choiceMira\\RL\\lstm_model",
                    help="Directory for saved models")
parser.add_argument("--batch_size",
                    type=int,
                    default=16,
                    help="Mini-batch size")
parser.add_argument("--num_epochs",
                    type=int,
                    default=200,
                    help="number of epochs")
parser.add_argument("--hidden-dim1",
                    type=int,
                    default=64,
                    help="Hidden dimension")
parser.add_argument("--hidden-dim2",
                    type=int,
                    default=128,
                    help="Hidden dimension")
parser.add_argument("--lr",
                    type=float,
                    default=1e-4,
                    help="Learning rate")
parser.add_argument("--weight_decay",
                    type=float,
                    default=0.001,
                    help="l_2 weight penalty")
parser.add_argument("--val_trials_wo_im",
                    type=int,
                    default=20,
                    help="Number of validation trials without improvement")

FLAGS = parser.parse_args(args=[])


class State(nn.Module):

    def __init__(self, features_size, embedding_dim, device):
        super(State, self).__init__()
        self.device = device
        self.features_size = features_size
        self.embedding_dim = embedding_dim
        self.lstm = nn.LSTMCell(input_size=self.embedding_dim *2 , hidden_size=self.embedding_dim *2 )
        self.initial_c = nn.Parameter(torch.randn(1, self.embedding_dim *2 ), requires_grad=True).to(
            device=self.device)
        self.initial_h = nn.Parameter(torch.randn(1, self.embedding_dim *2), requires_grad=True).to(
            device=self.device)
        self.reset_states()

    def reset_states(self):
        self.lstm_h = (torch.zeros(1, self.embedding_dim *2) + self.initial_h).to(device=self.device)
        self.lstm_c = (torch.zeros(1, self.embedding_dim *2) + self.initial_c).to(device=self.device)

    def forward(self, question_encode, answer):
        answer_vec = torch.unsqueeze(torch.ones(self.embedding_dim) * answer, 0)
        question_embedding = question_encode.to(device=self.device)
        answer_vec = answer_vec.to(device=self.device)
        answer_vec=answer_vec.squeeze()
        x = torch.cat((question_embedding,answer_vec), dim=0)
        x=x.unsqueeze(0)

        self.lstm_h, self.lstm_c = self.lstm(x, (self.lstm_h, self.lstm_c))
        return self.lstm_h.data.cpu().numpy()
