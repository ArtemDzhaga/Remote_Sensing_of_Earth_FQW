# -*- coding: utf-8 -*-
"""Оценка ML residual-модели на NPZ-патчах."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from dem.io.layout import outputs_root, resolve_out_dir
from dem.ml.dataset import DemPatchDataset
from dem.ml.model import build_model, default_device


def _metrics_from_errors(errors) -> dict[str, float]:
    import torch

    if errors.numel() == 0:
        return {"mae": float("nan"), "rmse": float("nan"), "psnr": float("nan")}
    mae = torch.mean(torch.abs(errors)).item()
    rmse = torch.sqrt(torch.mean(errors**2)).item()
    psnr = 20.0 * math.log10(1000.0 / max(rmse, 1e-12))
    return {"mae": mae, "rmse": rmse, "psnr": psnr}


def evaluate(args: argparse.Namespace) -> Path:
    import torch
    from torch.utils.data import DataLoader

    data_dir = Path(args.data_dir)
    split_dir = data_dir / args.split
    ds = DemPatchDataset(split_dir if split_dir.is_dir() else data_dir, augment=False)
    loader = DataLoader(ds, batch_size=args.batch_size, shuffle=False, num_workers=args.num_workers)

    device = args.device if args.device != "auto" else default_device()
    ckpt = torch.load(args.checkpoint, map_location=device)
    in_channels = int(ckpt.get("in_channels", 1))
    encoder_name = str(ckpt.get("encoder_name") or args.encoder_name)
    encoder_weights = ckpt.get("encoder_weights")
    model = build_model(
        in_channels=in_channels,
        classes=1,
        encoder_name=encoder_name,
        encoder_weights=encoder_weights,
        prefer_smp=not args.no_smp,
        require_smp=args.require_smp,
    ).to(device)
    model.load_state_dict(ckpt["model"])
    model.eval()

    baseline_errors = []
    corrected_errors = []
    rows = []

    with torch.no_grad():
        for batch in loader:
            x = batch["x"].to(device=device, dtype=torch.float32)
            y = batch["y"].to(device=device, dtype=torch.float32)
            valid = torch.isfinite(y)
            x = torch.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
            y_clean = torch.nan_to_num(y, nan=0.0, posinf=0.0, neginf=0.0)
            pred_residual = model(x)

            # Baseline "без ML" означает нулевая поправка, ошибка = 0 - residual.
            base_err = -y_clean
            corr_err = pred_residual - y_clean
            baseline_errors.append(base_err[valid].detach().cpu())
            corrected_errors.append(corr_err[valid].detach().cpu())

            for path, be, ce, vm in zip(batch["path"], base_err, corr_err, valid):
                rows.append(
                    {
                        "patch": str(path),
                        "pixels": int(vm.sum().item()),
                        "baseline": _metrics_from_errors(be[vm].detach().cpu()),
                        "corrected": _metrics_from_errors(ce[vm].detach().cpu()),
                    }
                )

    baseline_all = torch.cat(baseline_errors) if baseline_errors else torch.empty(0)
    corrected_all = torch.cat(corrected_errors) if corrected_errors else torch.empty(0)
    baseline = _metrics_from_errors(baseline_all)
    corrected = _metrics_from_errors(corrected_all)
    improvement = {
        "mae_abs": baseline["mae"] - corrected["mae"],
        "rmse_abs": baseline["rmse"] - corrected["rmse"],
        "mae_pct": 100.0 * (baseline["mae"] - corrected["mae"]) / baseline["mae"] if baseline["mae"] else float("nan"),
        "rmse_pct": 100.0 * (baseline["rmse"] - corrected["rmse"]) / baseline["rmse"] if baseline["rmse"] else float("nan"),
    }

    out_dir = resolve_out_dir(args.out_dir, lambda: outputs_root() / "ml_eval" / "insar_residual")
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "checkpoint": str(args.checkpoint),
        "data_dir": str(data_dir),
        "split": args.split,
        "patch_count": len(ds),
        "baseline": baseline,
        "corrected": corrected,
        "improvement": improvement,
        "checkpoint_metrics": ckpt.get("metrics", {}),
        "architecture": {
            "in_channels": in_channels,
            "encoder_name": encoder_name,
            "encoder_weights": encoder_weights,
            "prefer_smp": not args.no_smp,
        },
        "patches": rows,
    }
    json_path = out_dir / f"ml_eval_{args.split}.json"
    md_path = out_dir / f"ml_eval_{args.split}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# ML Evaluation: {args.split}",
        "",
        f"- checkpoint: `{args.checkpoint}`",
        f"- data_dir: `{data_dir}`",
        f"- patches: `{len(ds)}`",
        "",
        "| variant | MAE | RMSE | PSNR |",
        "|---|---:|---:|---:|",
        f"| baseline InSAR | {baseline['mae']:.3f} | {baseline['rmse']:.3f} | {baseline['psnr']:.3f} |",
        f"| ML-corrected | {corrected['mae']:.3f} | {corrected['rmse']:.3f} | {corrected['psnr']:.3f} |",
        "",
        "## Improvement",
        "",
        f"- MAE: `{improvement['mae_abs']:.3f}` m (`{improvement['mae_pct']:.2f}%`)",
        f"- RMSE: `{improvement['rmse_abs']:.3f}` m (`{improvement['rmse_pct']:.2f}%`)",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"patches: {len(ds)}")
    print(f"baseline:  MAE={baseline['mae']:.3f} RMSE={baseline['rmse']:.3f} PSNR={baseline['psnr']:.3f}")
    print(f"corrected: MAE={corrected['mae']:.3f} RMSE={corrected['rmse']:.3f} PSNR={corrected['psnr']:.3f}")
    print(f"improve:   MAE={improvement['mae_abs']:.3f}m ({improvement['mae_pct']:.2f}%) "
          f"RMSE={improvement['rmse_abs']:.3f}m ({improvement['rmse_pct']:.2f}%)")
    print(f"report: {md_path}")
    return md_path


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Оценить residual-модель на train/val/test NPZ-патчах.")
    p.add_argument("--checkpoint", required=True, type=Path)
    p.add_argument("--data-dir", required=True)
    p.add_argument("--split", default="test", choices=["train", "val", "test"])
    p.add_argument("--out-dir", default="")
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--num-workers", type=int, default=0)
    p.add_argument("--device", default="auto", choices=["auto", "cpu", "mps", "cuda"])
    p.add_argument("--encoder-name", default="resnet18")
    p.add_argument("--no-smp", action="store_true")
    p.add_argument("--require-smp", action="store_true")
    return p


def main() -> None:
    evaluate(build_parser().parse_args())


if __name__ == "__main__":
    main()
