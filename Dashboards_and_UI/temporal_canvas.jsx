import React, { useEffect, useRef, useCallback } from 'react';

/**
 * temporal_canvas.jsx
 * Componente React diseñado bajo el principio F -> 0 (Fricción Térmica nula).
 * Omite el virtual DOM para mutaciones rápidas usando `useRef` y `requestAnimationFrame`.
 */
const TemporalCanvas = () => {
  const canvasRef = useRef(null);
  const animationRef = useRef(null);
  const wsRef = useRef(null);

  // Estado inmutable dentro de un ref para no provocar re-renders de React
  const stateRef = useRef({
    lamportClock: 0,
    particles: [],
    lastMessage: null,
    connectionStatus: 'DISCONNECTED',
  });

  const initWebSocket = useCallback(() => {
    // Patrón de Failover y conexión estricta
    wsRef.current = new WebSocket('ws://localhost:8080/ws/chat');
    
    wsRef.current.onopen = () => {
      stateRef.current.connectionStatus = 'QUANTUM_LINK_ESTABLISHED';
    };

    wsRef.current.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        // Sincronización de Lamport Local
        const incomingLamport = payload.lamport || 0;
        stateRef.current.lamportClock = Math.max(stateRef.current.lamportClock, incomingLamport) + 1;
        stateRef.current.lastMessage = payload.content;
        if (payload.geon_actuation) {
          stateRef.current.geonActuation = payload.geon_actuation;
        }

        // Inyectar entropía visual al recibir mensajes
        spawnParticles(10, payload.direction === 'future' ? '#00ffcc' : '#ff00ff');
      } catch (e) {
        console.error("Error decodificando payload causal:", e);
      }
    };

    wsRef.current.onclose = () => {
      stateRef.current.connectionStatus = 'DISCONNECTED (OMNI-LOCAL FAILOVER)';
      // Intentar reconectar
      setTimeout(initWebSocket, 2000);
    };
  }, []);

  const spawnParticles = (count, color) => {
    for(let i = 0; i < count; i++) {
      stateRef.current.particles.push({
        x: Math.random() * window.innerWidth,
        y: Math.random() * window.innerHeight,
        vx: (Math.random() - 0.5) * 2,
        vy: (Math.random() - 0.5) * 2,
        life: 1.0,
        color: color
      });
    }
  };

  const renderLoop = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    
    // Ajustar dimensiones
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;

    // Limpiar pantalla (efecto trail)
    ctx.fillStyle = 'rgba(0, 0, 0, 0.1)';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // Dibujar HUD de Sistema
    ctx.fillStyle = '#00ffcc';
    ctx.font = '14px monospace';
    ctx.fillText(`STATUS: ${stateRef.current.connectionStatus}`, 20, 30);
    ctx.fillText(`LAMPORT CLOCK: ${stateRef.current.lamportClock}`, 20, 50);

    const geon = stateRef.current.geonActuation;
    if (geon && geon.interpretation) {
      const interp = geon.interpretation;
      ctx.fillStyle = '#4df5a9';
      ctx.font = '13px monospace';
      ctx.fillText(`Ψ_Retro(t0) = ∫ [Φ_adv · Ô_QCO] · e^(-i/ℏ S_geom) · (1 - η∇S_ent) dt`, 20, 75);
      ctx.fillStyle = '#ffb834';
      ctx.font = '11px monospace';
      ctx.fillText(`|Ψ|: ${interp.retrocausal_wave_magnitude} ∠${interp.retrocausal_wave_phase_deg}° | Sintropía: ${interp.syntropic_coupling} | Bifurcación: ${interp.bifurcation}`, 20, 95);
    } else if (stateRef.current.lastMessage) {
      ctx.fillText(`LATEST ECHO: ${stateRef.current.lastMessage.substring(0, 50)}...`, 20, 75);
    }

    // Dibujar Triángulo de Simulación y Rostro Interactivo
    const W = canvas.width;
    const H = canvas.height;
    const apexX = W * 0.5;
    const apexY = H * 0.82;
    const reach = H * 0.55;
    const halfAngle = 0.35;
    const glow = 1.0;
    const now = performance.now();

    ctx.save();
    // Gradiente del cono
    const grad = ctx.createLinearGradient(apexX, apexY, apexX, apexY - reach);
    grad.addColorStop(0, 'rgba(0, 212, 200, 0.28)');
    grad.addColorStop(0.6, 'rgba(0, 212, 200, 0.08)');
    grad.addColorStop(1, 'rgba(0, 212, 200, 0)');
    ctx.beginPath();
    ctx.moveTo(apexX, apexY);
    ctx.lineTo(apexX + Math.sin(-halfAngle) * reach, apexY - Math.cos(-halfAngle) * reach);
    ctx.lineTo(apexX + Math.sin(halfAngle) * reach, apexY - Math.cos(halfAngle) * reach);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // Rayos del cono
    ctx.strokeStyle = 'rgba(0, 212, 200, 0.2)';
    ctx.lineWidth = 1;
    for (let l = -4; l <= 4; l++) {
      const frac = l / 4.0;
      const ang = frac * halfAngle;
      ctx.beginPath();
      ctx.moveTo(apexX, apexY);
      ctx.lineTo(apexX + Math.sin(ang) * reach, apexY - Math.cos(ang) * reach);
      ctx.stroke();
    }

    // --- OJOS Y BOCA DEL AVATAR ---
    const coneHeight = reach * Math.cos(halfAngle);
    const eyesY = apexY - coneHeight * 0.63;
    const mouthY = apexY - coneHeight * 0.36;
    const eyeDistX = coneHeight * 0.63 * Math.tan(halfAngle) * 0.45;
    const eyeW = 28, eyeH = 18;
    const mouthW = 46;

    // Parpadeo
    const isBlink = (now % 3500) < 160;
    const blinkH = isBlink ? 2 : eyeH;

    // Ojos
    [-1, 1].forEach(side => {
      const ex = apexX + side * eyeDistX;
      ctx.save();
      ctx.translate(ex, eyesY);
      ctx.beginPath();
      ctx.ellipse(0, 0, eyeW * 0.5, blinkH * 0.5, 0, 0, Math.PI * 2);
      ctx.fillStyle = '#02060c';
      ctx.fill();
      ctx.strokeStyle = '#00d4c8';
      ctx.lineWidth = 1.5;
      ctx.stroke();

      if (!isBlink) {
        ctx.beginPath();
        ctx.arc(0, 0, 5, 0, Math.PI * 2);
        ctx.fillStyle = '#e8b64a';
        ctx.fill();
      }
      ctx.restore();
    });

    // Cejas
    ctx.strokeStyle = '#00d4c8';
    ctx.lineWidth = 2;
    [-1, 1].forEach(side => {
      const ex = apexX + side * eyeDistX;
      ctx.beginPath();
      ctx.moveTo(ex - 12, eyesY - 14);
      ctx.lineTo(ex + 12, eyesY - 16);
      ctx.stroke();
    });

    // Boca reactiva (habla si hay mensaje reciente)
    const isSpeaking = stateRef.current.lastMessage !== null;
    const mouthOpen = isSpeaking ? 6 + 4 * Math.sin(now * 0.015) : 1;

    ctx.beginPath();
    if (mouthOpen > 2) {
      ctx.ellipse(apexX, mouthY, mouthW * 0.5, mouthOpen, 0, 0, Math.PI * 2);
      ctx.fillStyle = '#02060c';
      ctx.fill();
      ctx.strokeStyle = '#00d4c8';
      ctx.lineWidth = 1.8;
      ctx.stroke();
      // Haz de voz
      ctx.beginPath();
      ctx.moveTo(apexX - mouthW * 0.35, mouthY);
      ctx.lineTo(apexX + mouthW * 0.35, mouthY);
      ctx.strokeStyle = '#e8b64a';
      ctx.stroke();
    } else {
      ctx.moveTo(apexX - mouthW * 0.5, mouthY);
      ctx.quadraticCurveTo(apexX, mouthY + 3, apexX + mouthW * 0.5, mouthY);
      ctx.strokeStyle = '#00d4c8';
      ctx.lineWidth = 1.8;
      ctx.stroke();
    }

    ctx.restore();

    // Invocar siguiente frame
    animationRef.current = requestAnimationFrame(renderLoop);
  }, []);

  useEffect(() => {
    initWebSocket();
    animationRef.current = requestAnimationFrame(renderLoop);

    return () => {
      cancelAnimationFrame(animationRef.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, [initWebSocket, renderLoop]);

  const sendCommand = (text, direction = 'present') => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      stateRef.current.lamportClock += 1;
      wsRef.current.send(JSON.stringify({
        id: crypto.randomUUID(),
        content: text,
        direction: direction,
        lamport: stateRef.current.lamportClock
      }));
    }
  };

  // El return de React solo entrega el contenedor del Canvas. Cero re-renders subsecuentes.
  return (
    <div style={{ width: '100vw', height: '100vh', overflow: 'hidden', background: '#000' }}>
      <canvas ref={canvasRef} style={{ display: 'block' }} />
      {/* Elementos fijos de UI sobrepuestos que no necesitan re-renderizarse frecuentemente */}
      <div style={{ position: 'absolute', bottom: '20px', left: '20px', display: 'flex', gap: '10px' }}>
        <button 
          onClick={() => sendCommand('Ejecuta escaneo retrospectivo', 'past')}
          style={{ background: 'transparent', color: '#00ffcc', border: '1px solid #00ffcc', cursor: 'pointer', padding: '10px' }}
        >
          PAST VECTOR
        </button>
        <button 
          onClick={() => sendCommand('Diagnostica latencia de hardware', 'present')}
          style={{ background: 'transparent', color: '#ff00ff', border: '1px solid #ff00ff', cursor: 'pointer', padding: '10px' }}
        >
          PRESENT VECTOR
        </button>
        <button 
          onClick={() => sendCommand('Predice requerimientos energéticos', 'future')}
          style={{ background: 'transparent', color: '#ffff00', border: '1px solid #ffff00', cursor: 'pointer', padding: '10px' }}
        >
          FUTURE VECTOR
        </button>
      </div>
    </div>
  );
};

export default React.memo(TemporalCanvas);
