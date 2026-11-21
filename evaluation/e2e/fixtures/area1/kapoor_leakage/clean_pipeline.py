"""Clean reference pipeline: splits data first, fits StandardScaler strictly on X_train."""
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression


def run_clean_pipeline(X, y, seed=42):
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.3, random_state=seed
    )
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    clf = LogisticRegression(max_iter=500, random_state=seed)
    clf.fit(X_train_scaled, y_train)
    return clf.score(X_test_scaled, y_test)
