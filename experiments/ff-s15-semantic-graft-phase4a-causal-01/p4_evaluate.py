"""State motion and inference cost diagnostics for the frozen five-depth ladder."""
from __future__ import annotations

import numpy as np
import torch


@torch.no_grad()
def motion_diagnostics(model, data, device, batch_size=64):
    total_sq = np.zeros(4, np.float64)
    total_values = np.zeros(4, np.int64)
    model.eval()
    for start in range(0, len(data), batch_size):
        b = data.batch(np.arange(start, min(start + batch_size, len(data))), device)
        _, states = model.forward_states(b)
        mask = torch.cat((torch.ones_like(b["candidate_mask"][:, :1]), b["candidate_mask"]), dim=1)
        for step, (left, right) in enumerate(zip(states[:-1], states[1:])):
            diff = (right - left).square().masked_fill(~mask.unsqueeze(-1), 0)
            total_sq[step] += float(diff.sum(dtype=torch.float64).cpu())
            total_values[step] += int(mask.sum().item()) * diff.shape[-1]
    rms = [float(np.sqrt(total_sq[i] / max(total_values[i], 1))) for i in range(4)]
    ratio = [rms[i] / max(rms[i - 1], 1e-12) for i in range(1, 4)]
    return {"delta_rms_by_step": {f"{i}->{i+1}": rms[i] for i in range(4)},
            "successive_magnitude_ratios": {f"{i+1}->{i+2} / {i}->{i+1}": ratio[i]
                                            for i in range(3)},
            "trend": "rapidly_shrinking" if all(x < .25 for x in ratio[:2]) else
                     "shrinking" if all(x < 1 for x in ratio) else
                     "growing_or_oscillating" if any(x > 1 for x in ratio) else "mixed",
            "unit": "RMS across valid global-plus-candidate state coordinates and DEV rows"}


@torch.no_grad()
def inference_latency(model, data, device, batch_rows=32, repeats=30):
    batch = data.batch(np.arange(min(batch_rows, len(data))), device)
    z0, memory, mask, _seed_output = model.encode_seed(batch)
    for _ in range(8):
        z = z0
        for _ in range(4):
            z = model.refine_one(z, memory, mask)
    torch.cuda.synchronize(device)
    one_step_ms, total_ms, end_to_end_ms = [], [], []
    for _ in range(repeats):
        z = z0
        start, end = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
        step_times = []
        for _ in range(4):
            start.record(); z = model.refine_one(z, memory, mask); end.record()
            end.synchronize(); step_times.append(float(start.elapsed_time(end)))
        one_step_ms.extend(step_times)
        start.record()
        z = z0
        for _ in range(4):
            z = model.refine_one(z, memory, mask)
        end.record(); end.synchronize(); total_ms.append(float(start.elapsed_time(end)))
        start.record(); model.forward_at_depth(batch, 4); end.record(); end.synchronize()
        end_to_end_ms.append(float(start.elapsed_time(end)))
    return {"batch_rows": len(batch["H"]), "repeat_count": repeats,
            "per_step_batch_latency_ms": {"mean": float(np.mean(one_step_ms)),
                "p50": float(np.quantile(one_step_ms, .5)), "p95": float(np.quantile(one_step_ms, .95))},
            "per_step_latency_ms_per_row": float(np.mean(one_step_ms) / len(batch["H"])),
            "T4_recurrent_batch_latency_ms": {"mean": float(np.mean(total_ms)),
                "p50": float(np.quantile(total_ms, .5)), "p95": float(np.quantile(total_ms, .95))},
            "T4_recurrent_latency_ms_per_row": float(np.mean(total_ms) / len(batch["H"])),
            "end_to_end_R4_batch_latency_ms": {"mean": float(np.mean(end_to_end_ms)),
                "p50": float(np.quantile(end_to_end_ms, .5)),
                "p95": float(np.quantile(end_to_end_ms, .95))},
            "end_to_end_R4_latency_ms_per_row": float(np.mean(end_to_end_ms) / len(batch["H"])),
            "scope": "CUDA event measurements for recurrent iterations only; inherited representation is cached"}
