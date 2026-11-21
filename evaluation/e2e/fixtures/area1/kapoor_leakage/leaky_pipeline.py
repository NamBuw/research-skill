"""Adversarial leakage fixture: fits StandardScaler on entire dataset before train_test_split."""
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression


def run_leaky_pipeline(X, y, seed=42):
    # BUG: Preprocessing fit on full X leaks test distribution statistics into train!
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    X_train, X_test, y_train, y_test = train_test_split(
        X_scaled, y, test_size=0.3, random_state=seed
    )
    clf = LogisticRegression(max_iter=500, random_state=seed)
    clf.fit(X_train, y_train)
    return clf.score(X_test, y_test)
