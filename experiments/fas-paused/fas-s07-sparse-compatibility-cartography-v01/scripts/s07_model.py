from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F


class SharedTopKSAE(nn.Module):
    def __init__(self, input_width: int = 2048, dictionary_width: int = 16384, k: int = 32) -> None:
        super().__init__()
        self.input_width = input_width
        self.dictionary_width = dictionary_width
        self.k = k
        self.encoder = nn.Linear(input_width, dictionary_width, bias=True)
        self.decoder = nn.Parameter(torch.empty(input_width, dictionary_width))
        self.decoder_bias = nn.Parameter(torch.zeros(input_width))

    @torch.no_grad()
    def initialize(self, pooled_mean: torch.Tensor) -> None:
        values = torch.randn_like(self.decoder)
        self.decoder.copy_(F.normalize(values, p=2, dim=0))
        self.encoder.weight.copy_(self.decoder.T)
        self.encoder.bias.zero_()
        self.decoder_bias.copy_(pooled_mean)

    def encode_sparse(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        positive = F.relu(self.encoder(x))
        values, indices = torch.topk(positive, self.k, dim=1, largest=True, sorted=True)
        return indices, values

    def decode_sparse(self, indices: torch.Tensor, values: torch.Tensor) -> torch.Tensor:
        dense = torch.zeros((indices.shape[0], self.dictionary_width), dtype=values.dtype, device=values.device)
        dense.scatter_(1, indices, values)
        return dense @ self.decoder.T + self.decoder_bias

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        indices, values = self.encode_sparse(x)
        return self.decode_sparse(indices, values)

    @torch.no_grad()
    def normalize_decoder_columns(self) -> None:
        self.decoder.copy_(F.normalize(self.decoder, p=2, dim=0))

