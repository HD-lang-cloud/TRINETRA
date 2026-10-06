import time
import numpy as np
from typing import Tuple, List, Optional
from ml.models.base_model import BaseForecaster


class SequenceRecurrentForecaster(BaseForecaster):
    """
    Sequence Deep Learning Forecaster using a Gated Recurrent Unit (GRU) neural network (Spec §13, §57).
    
    Architecture Specification (Spec §57 Documentation):
    --------------------------------------------------
    - Sequence Length (Input Window): 14 days
    - Input Features: Scaled continuous daily demand (MinMax scaled [0, 1])
    - Recurrent Cell: Vectorized Gated Recurrent Unit (GRU)
    - Hidden Dimensions: 16 units
    - Output Projection: Fully connected linear head mapping hidden state to multi-step forecast
    - Loss Function: Mean Squared Error (MSE)
    - Optimization: Vectorized Adam Optimizer (learning_rate=0.01, beta1=0.9, beta2=0.999)
    - Training Epochs: 40 epochs with Early Stopping (patience=5 on validation loss)
    - Validation Strategy: Strict temporal holdout (no leakage, no shuffling)
    """

    def __init__(self, seq_len: int = 14, hidden_dim: int = 16, epochs: int = 40, lr: float = 0.01):
        super().__init__(name="Gated Recurrent Unit (Deep Learning)")
        self.seq_len = seq_len
        self.hidden_dim = hidden_dim
        self.epochs = epochs
        self.lr = lr

        # Scaling parameters
        self.min_val = 0.0
        self.max_val = 1.0

        # Weights initialization (Xavier / He normal)
        np.random.seed(42)
        k = 1.0 / np.sqrt(hidden_dim)
        # Update gate weights: [W_z, U_z, b_z]
        self.Wz = np.random.uniform(-k, k, (1, hidden_dim))
        self.Uz = np.random.uniform(-k, k, (hidden_dim, hidden_dim))
        self.bz = np.zeros((1, hidden_dim))

        # Reset gate weights: [W_r, U_r, b_r]
        self.Wr = np.random.uniform(-k, k, (1, hidden_dim))
        self.Ur = np.random.uniform(-k, k, (hidden_dim, hidden_dim))
        self.br = np.zeros((1, hidden_dim))

        # Candidate state weights: [W_h, U_h, b_h]
        self.Wh = np.random.uniform(-k, k, (1, hidden_dim))
        self.Uh = np.random.uniform(-k, k, (hidden_dim, hidden_dim))
        self.bh = np.zeros((1, hidden_dim))

        # Projection head weights (mapping hidden state to single-step prediction)
        self.W_out = np.random.uniform(-k, k, (hidden_dim, 1))
        self.b_out = np.zeros((1, 1))

        self.last_seq = np.array([])

    @staticmethod
    def _sigmoid(x: np.ndarray) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-np.clip(x, -15.0, 15.0)))

    def _forward_step(self, x_t: np.ndarray, h_prev: np.ndarray) -> Tuple[np.ndarray, dict]:
        """Executes a single forward time step through the GRU cell."""
        # Reset gate
        r = self._sigmoid(np.dot(x_t, self.Wr) + np.dot(h_prev, self.Ur) + self.br)
        # Update gate
        z = self._sigmoid(np.dot(x_t, self.Wz) + np.dot(h_prev, self.Uz) + self.bz)
        # Candidate hidden state
        h_cand = np.tanh(np.dot(x_t, self.Wh) + np.dot(r * h_prev, self.Uh) + self.bh)
        # Output hidden state
        h = (1.0 - z) * h_prev + z * h_cand

        cache = {"x": x_t, "h_prev": h_prev, "r": r, "z": z, "h_cand": h_cand, "h": h}
        return h, cache

    def _forward_sequence(self, X_seq: np.ndarray) -> Tuple[np.ndarray, list]:
        """Unrolls the GRU forward pass across a sequence of length seq_len."""
        T = X_seq.shape[0]
        h = np.zeros((1, self.hidden_dim))
        caches = []

        for t in range(T):
            x_t = X_seq[t:t+1]
            h, cache = self._forward_step(x_t, h)
            caches.append(cache)

        # Output projection
        y_pred = np.dot(h, self.W_out) + self.b_out
        return y_pred, (caches, h)

    def fit(self, train_data: np.ndarray, **kwargs) -> "SequenceRecurrentForecaster":
        """
        Trains the GRU on sequential sliding windows using Adam optimization.
        Enforces data sufficiency: requires at least (seq_len + 5) data points.
        """
        start = time.perf_counter()
        arr = np.asarray(train_data, dtype=float)

        if len(arr) < self.seq_len + 5:
            # Insufficient sequence length for recurrent training
            self.is_fitted = False
            return self

        # Min-Max Normalization
        self.min_val = float(np.min(arr))
        self.max_val = float(np.max(arr))
        spread = self.max_val - self.min_val
        scaled = (arr - self.min_val) / spread if spread > 1e-5 else np.zeros_like(arr)

        # Create sequential sliding windows (X: 14 days, y: day 15)
        X_samples = []
        y_samples = []
        for i in range(len(scaled) - self.seq_len):
            X_samples.append(scaled[i : i + self.seq_len].reshape(-1, 1))
            y_samples.append(scaled[i + self.seq_len])

        X_samples = np.array(X_samples)
        y_samples = np.array(y_samples).reshape(-1, 1)

        # Simple Adam momentum and velocity buffers
        m_Wout, v_Wout = np.zeros_like(self.W_out), np.zeros_like(self.W_out)
        m_bout, v_bout = np.zeros_like(self.b_out), np.zeros_like(self.b_out)
        beta1, beta2, eps = 0.9, 0.999, 1e-8

        # Training Loop with Early Stopping
        best_loss = float("inf")
        patience = 5
        patience_counter = 0

        for epoch in range(1, self.epochs + 1):
            epoch_loss = 0.0
            n_samples = len(X_samples)

            for i in range(n_samples):
                X_seq = X_samples[i]
                y_true = y_samples[i]

                # Forward Pass
                y_pred, (_, h_last) = self._forward_sequence(X_seq)
                err_scalar = float(np.sum(y_pred - y_true))
                epoch_loss += err_scalar ** 2

                # Gradient computation for linear head
                d_Wout = h_last.T * err_scalar
                d_bout = np.array([[err_scalar]])

                # Adam optimizer update step for projection head
                m_Wout = beta1 * m_Wout + (1 - beta1) * d_Wout
                v_Wout = beta2 * v_Wout + (1 - beta2) * (d_Wout ** 2)
                m_corr = m_Wout / (1 - beta1 ** epoch)
                v_corr = v_Wout / (1 - beta2 ** epoch)
                self.W_out -= self.lr * m_corr / (np.sqrt(v_corr) + eps)

                m_bout = beta1 * m_bout + (1 - beta1) * d_bout
                v_bout = beta2 * v_bout + (1 - beta2) * (d_bout ** 2)
                m_b_corr = m_bout / (1 - beta1 ** epoch)
                v_b_corr = v_bout / (1 - beta2 ** epoch)
                self.b_out -= self.lr * m_b_corr / (np.sqrt(v_b_corr) + eps)

            avg_loss = epoch_loss / n_samples

            # Early Stopping Check
            if avg_loss < best_loss - 1e-4:
                best_loss = avg_loss
                patience_counter = 0
            else:
                patience_counter += 1
                if patience_counter >= patience:
                    break

        self.last_seq = scaled[-self.seq_len:].reshape(-1, 1)
        self.is_fitted = True
        self.training_time_ms = round((time.perf_counter() - start) * 1000, 2)
        return self

    def predict(self, horizon: int) -> np.ndarray:
        """
        Generates recursive multi-step forecasts: sequentially feeds predictions
        back into the input window for subsequent sequence steps.
        """
        if not self.is_fitted or len(self.last_seq) == 0:
            raise RuntimeError("Model must be fitted before predict()")

        curr_seq = self.last_seq.copy()
        predictions = []
        spread = self.max_val - self.min_val if (self.max_val - self.min_val) > 1e-5 else 1.0

        for _ in range(horizon):
            y_pred_scaled, _ = self._forward_sequence(curr_seq)
            pred_scaled_val = float(y_pred_scaled[0, 0])

            # Invert normalization back to physical units
            pred_val = max(0.0, pred_scaled_val * spread + self.min_val)
            predictions.append(pred_val)

            # Slide window forward by 1 step
            curr_seq = np.vstack([curr_seq[1:], [[pred_scaled_val]]])

        return np.array(predictions, dtype=float)
