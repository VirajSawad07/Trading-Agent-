"""Train LightGBM Machine Learning Signal Model with Walk-Forward Validation."""

import argparse
import os
import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from rich.console import Console
from rich.table import Table
from sklearn.metrics import classification_report, accuracy_score
from src.features.alpha_features import create_ml_dataset, get_feature_columns


from typing import Optional

def train_model(
    csv_path: str = "data/raw/XAUUSD_M15.csv",
    horizon_bars: int = 8,
    threshold_pct: float = 0.002,
    output_dir: str = "models/ml",
    output_name: Optional[str] = None,
):
    console = Console()
    console.print(f"[bold cyan][ML Training][/bold cyan] Loading data from {csv_path}...")
    df = pd.read_csv(csv_path, index_col=0, parse_dates=True)

    console.print(f"[bold cyan][ML Training][/bold cyan] Engineering alpha features & forward returns (H={horizon_bars} bars)...")
    X, y = create_ml_dataset(df, horizon_bars=horizon_bars, threshold_pct=threshold_pct)
    
    total_samples = len(X)
    console.print(f"[bold cyan][ML Training][/bold cyan] Total clean samples: {total_samples}")

    # Class balance check
    class_counts = y.value_counts().to_dict()
    console.print(f"[bold cyan][ML Training][/bold cyan] Class balance: HOLD(0): {class_counts.get(0, 0)}, BUY(1): {class_counts.get(1, 0)}, SELL(2): {class_counts.get(2, 0)}")

    # Chronological Walk-Forward Split (Strictly NO random shuffling)
    train_idx = int(total_samples * 0.70)
    val_idx = int(total_samples * 0.85)

    X_train, y_train = X.iloc[:train_idx], y.iloc[:train_idx]
    X_val, y_val = X.iloc[train_idx:val_idx], y.iloc[train_idx:val_idx]
    X_test, y_test = X.iloc[val_idx:], y.iloc[val_idx:]

    console.print(f"[bold cyan][ML Training][/bold cyan] Chronological Split: Train={len(X_train)}, Val={len(X_val)}, Test={len(X_test)}")

    # Initialize LightGBM Classifier with anti-overfitting regularization
    model = LGBMClassifier(
        n_estimators=200,
        learning_rate=0.03,
        num_leaves=15,
        max_depth=4,
        min_child_samples=40,
        subsample=0.8,
        colsample_bytree=0.8,
        n_jobs=2,
        random_state=42,
        verbosity=-1,
    )

    console.print("[bold cyan][ML Training][/bold cyan] Fitting LightGBM model...")
    model.fit(
        X_train,
        y_train,
        eval_set=[(X_val, y_val)],
    )

    # Evaluate on Untouched Out-Of-Sample Test Set
    test_preds = model.predict(X_test)
    test_acc = accuracy_score(y_test, test_preds)
    report = classification_report(y_test, test_preds, target_names=["HOLD", "BUY", "SELL"], output_dict=True)

    # Display Metrics Table
    table = Table(title="[bold green]Out-of-Sample Test Evaluation[/bold green]")
    table.add_column("Class", style="cyan")
    table.add_column("Precision", style="magenta")
    table.add_column("Recall", style="green")
    table.add_column("F1-Score", style="yellow")
    table.add_column("Support", style="white")

    for cls_name in ["HOLD", "BUY", "SELL"]:
        if cls_name in report:
            r = report[cls_name]
            table.add_row(cls_name, f"{r['precision']:.3f}", f"{r['recall']:.3f}", f"{r['f1-score']:.3f}", str(int(r['support'])))

    console.print(table)
    console.print(f"[bold green]Overall Test Accuracy:[/bold green] {test_acc:.3%}")

    # Feature Importance Table
    feature_names = get_feature_columns()
    importances = model.feature_importances_
    feat_df = pd.DataFrame({"feature": feature_names, "importance": importances}).sort_values("importance", ascending=False)

    feat_table = Table(title="[bold gold1]Top 10 Alpha Features by Gain[/bold gold1]")
    feat_table.add_column("Rank", style="dim")
    feat_table.add_column("Feature", style="bold cyan")
    feat_table.add_column("Importance (Splits)", style="bold green")

    for rank, (_, row) in enumerate(feat_df.head(10).iterrows(), 1):
        feat_table.add_row(str(rank), row["feature"], str(int(row["importance"])))

    console.print(feat_table)

    # Save Model Artifact
    os.makedirs(output_dir, exist_ok=True)
    if not output_name:
        basename = os.path.basename(csv_path).lower()
        if "m5" in basename:
            output_name = "lightgbm_gold_m5.pkl"
        else:
            output_name = "lightgbm_gold_m15.pkl"

    model_path = os.path.join(output_dir, output_name)
    
    artifact = {
        "model": model,
        "feature_names": feature_names,
        "horizon_bars": horizon_bars,
        "threshold_pct": threshold_pct,
        "test_metrics": report,
    }
    joblib.dump(artifact, model_path)
    console.print(f"[bold green]Successfully saved trained model to {model_path}![/bold green]")
    return model_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=str, default="data/raw/XAUUSD_M15.csv")
    parser.add_argument("--horizon", type=int, default=8, help="Forward return horizon bars")
    parser.add_argument("--threshold", type=float, default=0.002, help="Target threshold return")
    parser.add_argument("--output", type=str, default="", help="Custom output pickle filename")
    args = parser.parse_args()

    train_model(
        csv_path=args.csv,
        horizon_bars=args.horizon,
        threshold_pct=args.threshold,
        output_name=args.output or None,
    )
