"""Stage-2 meta-classifier: L2 logistic regression with in-fold imputation and standardisation."""
from __future__ import annotations

import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


def make_model(C: float) -> Pipeline:
    return Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
        ("logit", LogisticRegression(C=float(C), solver="lbfgs", max_iter=2000)),
    ])


def fit_predict(X_train: np.ndarray, y_train: np.ndarray, X_test: np.ndarray, C: float):
    """Fit on the train fold only, predict the test fold. Returns (p_test, fitted_model)."""
    y_train = np.asarray(y_train, int)
    if len(np.unique(y_train)) < 2:
        p = np.full(len(X_test), float(y_train.mean()) if len(y_train) else 0.5)
        return p, None
    m = make_model(C).fit(np.asarray(X_train, float), y_train)
    return m.predict_proba(np.asarray(X_test, float))[:, 1], m
