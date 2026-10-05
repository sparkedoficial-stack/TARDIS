import numpy as np
from scipy.fft import fft, ifft
import math

class ECCAPredictionEngine:
    """
    ECCA Spectral Extrapolator.
    Transmuta búferes de texto históricos en ondas espectrales, avanza la fase (theta + pi/4)
    y retorna ecos predictivos y entropía estructural.
    """
    def __init__(self):
        self.phase_shift = math.pi / 4  # Bifurcación Causal de avance
        self.syntropy_threshold = 0.42

    def calculate_entropy(self, text: str) -> float:
        """
        Calcula la entropía de Shannon (S_ent) del buffer de entrada.
        """
        if not text:
            return 0.0
        probabilities = [float(text.count(c)) / len(text) for c in dict.fromkeys(list(text))]
        entropy = -sum(p * math.log2(p) for p in probabilities)
        return round(entropy, 4)

    def text_to_vector(self, text: str) -> np.ndarray:
        """Vectoriza texto a código ASCII/UTF-8."""
        return np.array([ord(c) for c in text], dtype=float)

    def vector_to_text(self, vector: np.ndarray) -> str:
        """Decodifica un vector devuelto por IFFT en texto probable."""
        chars = []
        for val in vector.real:
            # Acotamos y redondeamos para evitar errores ASCII
            v = int(round(val))
            v = max(32, min(126, v)) # Limitar a caracteres imprimibles
            chars.append(chr(v))
        return "".join(chars)

    def extrapolate_future(self, history_buffer: str) -> dict:
        """
        Aplica la fórmula matemática retrocausal para extrapolar la 
        respuesta predictiva.
        """
        if not history_buffer:
            return {"echo": "", "entropy": 0.0, "status": "void"}

        # 1. Monitoreo Entrópico
        entropy = self.calculate_entropy(history_buffer)
        
        # 2. Vectorización
        signal = self.text_to_vector(history_buffer)
        
        # Padding a potencia de 2 para mejor FFT (opcional, pero ayuda)
        n = len(signal)
        n_padded = 1 if n == 0 else 2**(n - 1).bit_length()
        if n_padded > n:
            signal = np.pad(signal, (0, n_padded - n), 'constant')

        # 3. Transformada FFT
        spectrum = fft(signal)
        
        # 4. Desplazamiento de Fase (Bifurcación Causal)
        # Multiplicar por e^(i * (pi/4))
        phase_shifter = np.exp(1j * self.phase_shift)
        shifted_spectrum = spectrum * phase_shifter
        
        # 5. Transformada Inversa IFFT
        extrapolated_signal = ifft(shifted_spectrum)
        
        # 6. Decodificación a Eco
        # Solo usamos la longitud original (n) para quitar el padding
        echo_text = self.vector_to_text(extrapolated_signal[:n])

        return {
            "echo": echo_text,
            "entropy": entropy,
            "syntropy_adjustment_needed": entropy > 4.5, # Umbral de caos
            "status": "extrapolated"
        }

if __name__ == "__main__":
    engine = ECCAPredictionEngine()
    print("--- PRUEBA DE MOTOR ECCA FFT ---")
    test_buffer = "El sistema esta operando nominalmente. Se requiere despliegue."
    res = engine.extrapolate_future(test_buffer)
    print(f"Original: {test_buffer}")
    print(f"Extrapolado (Fase +pi/4): {res['echo']}")
    print(f"Entropía: {res['entropy']}")
