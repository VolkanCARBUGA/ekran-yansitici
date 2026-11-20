(() => {
  "use strict";

  const PKT_JPEG = 0x03;

  const stage = document.getElementById("stage");
  const canvas = document.getElementById("screen");
  const ctx = canvas.getContext("2d", { alpha: false, desynchronized: true });

  const overlay = document.getElementById("overlay");
  const overlayTitle = document.getElementById("overlay-title");
  const overlaySubtitle = document.getElementById("overlay-subtitle");
  const btnRetry = document.getElementById("btn-retry");

  const btnFullscreen = document.getElementById("btn-fullscreen");
  const btnZoomReset = document.getElementById("btn-zoom-reset");

  let ws = null;
  let reconnectTimer = null;
  let reconnectAttempt = 0;
  let lastFrameAt = performance.now();
  let jpegDecoding = false;

  let frameWidth = 1440;
  let frameHeight = 900;
  let baseCssW = 0;
  let baseCssH = 0;

  // İki parmak yakınlaştırma (pinch-to-zoom) ve kaydırma (pan) durumu
  let zoom = 1.0;
  let panX = 0;
  let panY = 0;
  const MIN_ZOOM = 1.0;
  const MAX_ZOOM = 4.0;

  async function requestWakeLock() {
    if ("wakeLock" in navigator) {
      try {
        await navigator.wakeLock.request("screen");
      } catch (_) {}
    }
  }
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") requestWakeLock();
  });

  // ── Ekran Boyutlandırma & Yakınlaştırma ────────────────────────────────

  function clampPan() {
    if (zoom <= 1.001) {
      zoom = 1.0;
      panX = 0;
      panY = 0;
      return;
    }
    const vw = stage.clientWidth || window.innerWidth;
    const vh = stage.clientHeight || window.innerHeight;
    const scaledW = baseCssW * zoom;
    const scaledH = baseCssH * zoom;
    const maxPanX = Math.max(0, (scaledW - vw) / 2);
    const maxPanY = Math.max(0, (scaledH - vh) / 2);
    panX = Math.max(-maxPanX, Math.min(maxPanX, panX));
    panY = Math.max(-maxPanY, Math.min(maxPanY, panY));
  }

  function applyTransform() {
    clampPan();
    if (zoom <= 1.001) {
      canvas.style.transform = "";
      btnZoomReset.classList.add("hidden");
    } else {
      canvas.style.transform = `translate3d(${panX.toFixed(1)}px, ${panY.toFixed(1)}px, 0) scale(${zoom.toFixed(3)})`;
      btnZoomReset.textContent = `${Math.round(zoom * 100)}%`;
      btnZoomReset.classList.remove("hidden");
    }
  }

  function fitCanvasToViewport() {
    const vw = stage.clientWidth || window.innerWidth;
    const vh = stage.clientHeight || window.innerHeight;
    const aspect = frameWidth / frameHeight;
    const viewAspect = vw / vh;

    if (viewAspect > aspect) {
      baseCssH = vh;
      baseCssW = Math.round(vh * aspect);
    } else {
      baseCssW = vw;
      baseCssH = Math.round(vw / aspect);
    }
    canvas.style.width = `${baseCssW}px`;
    canvas.style.height = `${baseCssH}px`;
    applyTransform();
  }

  window.addEventListener("resize", fitCanvasToViewport);
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", fitCanvasToViewport);
  }

  function ensureCanvasResolution(w, h) {
    if (w > 0 && h > 0 && (canvas.width !== w || canvas.height !== h)) {
      canvas.width = w;
      canvas.height = h;
      frameWidth = w;
      frameHeight = h;
      fitCanvasToViewport();
    }
  }

  // ── Görüntü Çözme ───────────────────────────────────────────────────────

  async function decodeJpegPacket(payload) {
    if (jpegDecoding) return;
    jpegDecoding = true;
    try {
      const blob = new Blob([payload], { type: "image/jpeg" });
      const bitmap = await createImageBitmap(blob);
      ensureCanvasResolution(bitmap.width, bitmap.height);
      ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      bitmap.close();
      lastFrameAt = performance.now();
    } catch (_) {
    } finally {
      jpegDecoding = false;
    }
  }

  // ── WebSocket Bağlantısı ────────────────────────────────────────────────

  function sendJson(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(obj));
    }
  }

  function connect() {
    clearTimeout(reconnectTimer);
    if (ws) {
      try { ws.close(); } catch (_) {}
      ws = null;
    }

    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${proto}//${location.host}/ws`;

    overlayTitle.textContent = reconnectAttempt > 0
      ? `Yeniden Bağlanılıyor (${reconnectAttempt})...`
      : "Bilgisayara Bağlanılıyor...";
    overlaySubtitle.textContent = "Ekran akışı başlatılıyor";
    overlay.classList.remove("hidden");
    btnRetry.classList.add("hidden");

    ws = new WebSocket(wsUrl);
    ws.binaryType = "arraybuffer";

    ws.onopen = () => {
      reconnectAttempt = 0;
      lastFrameAt = performance.now();
      overlay.classList.add("hidden");
      requestWakeLock();
      sendJson({ type: "hello", protocol: 2, codec: "jpeg" });
      sendJson({ type: "set_touch_enabled", enabled: true });
    };

    ws.onmessage = (ev) => {
      if (typeof ev.data === "string") return;
      const buf = new Uint8Array(ev.data);
      if (buf.length < 2) return;
      if (buf[0] === PKT_JPEG) {
        decodeJpegPacket(buf.subarray(1));
      }
    };

    ws.onerror = () => {};
    ws.onclose = () => {
      reconnectAttempt++;
      const delay = Math.min(5000, 1000 * Math.min(reconnectAttempt, 4));
      overlay.classList.remove("hidden");
      overlayTitle.textContent = "Bağlantı Kesildi";
      overlaySubtitle.textContent = `${Math.round(delay / 1000)} sn içinde yeniden bağlanılacak...`;
      btnRetry.classList.remove("hidden");
      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(connect, delay);
    };
  }

  // Anti-donma bekçisi (yalnızca aktif sekmede)
  setInterval(() => {
    if (
      document.visibilityState === "visible" &&
      ws &&
      ws.readyState === WebSocket.OPEN &&
      performance.now() - lastFrameAt > 6000
    ) {
      lastFrameAt = performance.now();
      try { ws.close(); } catch (_) {}
    }
  }, 2000);

  // ── Dokunmatik Kontrol + İki Parmak Yakınlaştırma / Uzaklaştırma ───────

  const pointers = new Map();
  let startPos = null;
  let isDragging = false;
  let isMouseDown = false;
  let longPressTimer = null;
  let lastTapTime = 0;

  // Pinch-zoom & pan state
  let isPinching = false;
  let pinchStartDist = 0;
  let pinchStartZoom = 1.0;
  let pinchStartMid = null;
  let pinchStartPanX = 0;
  let pinchStartPanY = 0;

  function toNormalized(clientX, clientY) {
    // getBoundingClientRect() aktif zoom/pan dönüşümünü otomatik içerir!
    const rect = canvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return null;
    const nx = (clientX - rect.left) / rect.width;
    const ny = (clientY - rect.top) / rect.height;
    if (nx < -0.02 || nx > 1.02 || ny < -0.02 || ny > 1.02) return null;
    return {
      x: Math.max(0, Math.min(1, nx)),
      y: Math.max(0, Math.min(1, ny)),
    };
  }

  function getTwoPointerMetrics() {
    const pts = Array.from(pointers.values());
    const dx = pts[1].x - pts[0].x;
    const dy = pts[1].y - pts[0].y;
    return {
      dist: Math.hypot(dx, dy),
      midX: (pts[0].x + pts[1].x) / 2,
      midY: (pts[0].y + pts[1].y) / 2,
    };
  }

  stage.addEventListener("pointerdown", (e) => {
    if (e.target.closest(".controls") || e.target.closest(".overlay")) return;
    stage.setPointerCapture(e.pointerId);
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });

    // 2 parmak: Yakınlaştırma / uzaklaştırma (pinch-zoom) ve pan başlat
    if (pointers.size === 2) {
      clearTimeout(longPressTimer);
      longPressTimer = null;
      if (isMouseDown) {
        sendJson({ type: "mouse_up", button: "left" });
        isMouseDown = false;
      }
      isDragging = false;
      startPos = null;
      isPinching = true;

      const m = getTwoPointerMetrics();
      pinchStartDist = Math.max(10, m.dist);
      pinchStartZoom = zoom;
      pinchStartMid = { x: m.midX, y: m.midY };
      pinchStartPanX = panX;
      pinchStartPanY = panY;
      return;
    }

    if (pointers.size > 2) return;

    isPinching = false;
    startPos = { x: e.clientX, y: e.clientY };
    isDragging = false;
    isMouseDown = false;

    const norm = toNormalized(e.clientX, e.clientY);
    if (norm) {
      longPressTimer = setTimeout(() => {
        sendJson({ type: "click", button: "right", x: norm.x, y: norm.y });
        if (navigator.vibrate) navigator.vibrate(25);
        longPressTimer = null;
      }, 450);
    }
  });

  stage.addEventListener("pointermove", (e) => {
    if (!pointers.has(e.pointerId)) return;
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });

    // İki parmakla yakınlaştırma / uzaklaştırma + kaydırma
    if (pointers.size >= 2 && isPinching && pinchStartMid) {
      const m = getTwoPointerMetrics();
      const ratio = m.dist / pinchStartDist;
      const newZoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, pinchStartZoom * ratio));

      // Parmağın orta noktasına göre doğal yakınlaştırma
      const vw = stage.clientWidth || window.innerWidth;
      const vh = stage.clientHeight || window.innerHeight;
      const cx = vw / 2;
      const cy = vh / 2;
      const scaleChange = newZoom / pinchStartZoom;

      zoom = newZoom;
      panX = (m.midX - cx) - ((pinchStartMid.x - cx - pinchStartPanX) * scaleChange);
      panY = (m.midY - cy) - ((pinchStartMid.y - cy - pinchStartPanY) * scaleChange);
      applyTransform();
      return;
    }

    if (isPinching || !startPos) return;

    // Tek parmak: bilgisayarda sürükle-bırak
    const totalMove = Math.hypot(e.clientX - startPos.x, e.clientY - startPos.y);
    if (totalMove > 7) {
      if (!isDragging) {
        clearTimeout(longPressTimer);
        longPressTimer = null;
        isDragging = true;
        const normStart = toNormalized(startPos.x, startPos.y);
        if (normStart) {
          sendJson({ type: "mouse_down", button: "left", x: normStart.x, y: normStart.y });
          isMouseDown = true;
        }
      }
      const norm = toNormalized(e.clientX, e.clientY);
      if (norm) sendJson({ type: "mouse_move", x: norm.x, y: norm.y });
    }
  });

  function handlePointerEnd(e) {
    if (!pointers.has(e.pointerId)) return;
    pointers.delete(e.pointerId);

    if (isPinching) {
      if (pointers.size === 0) {
        isPinching = false;
        pinchStartMid = null;
      }
      return;
    }

    const hadLongPress = longPressTimer !== null;
    clearTimeout(longPressTimer);
    longPressTimer = null;

    if (isMouseDown) {
      const norm = toNormalized(e.clientX, e.clientY);
      if (norm) sendJson({ type: "mouse_up", button: "left", x: norm.x, y: norm.y });
      isMouseDown = false;
    } else if (hadLongPress && !isDragging && startPos) {
      const norm = toNormalized(startPos.x, startPos.y);
      if (norm) {
        const now = performance.now();
        const count = (now - lastTapTime < 300) ? 2 : 1;
        lastTapTime = now;
        sendJson({ type: "click", button: "left", x: norm.x, y: norm.y, count });
      }
    }

    isDragging = false;
    startPos = null;
  }

  stage.addEventListener("pointerup", handlePointerEnd);
  stage.addEventListener("pointercancel", handlePointerEnd);

  // ── Tam Ekran & Zoom Sıfırlama ──────────────────────────────────────────

  function updateFullscreenButton() {
    const isFs = Boolean(document.fullscreenElement);
    btnFullscreen.textContent = isFs ? "🗗 Tam Ekrandan Çık" : "⛶ Tam Ekran";
    setTimeout(fitCanvasToViewport, 80);
  }

  btnFullscreen.addEventListener("click", async () => {
    try {
      if (!document.fullscreenElement) {
        await document.documentElement.requestFullscreen();
        if (screen.orientation && screen.orientation.lock) {
          screen.orientation.lock("landscape").catch(() => {});
        }
        requestWakeLock();
      } else {
        await document.exitFullscreen();
      }
    } catch (_) {}
  });

  document.addEventListener("fullscreenchange", updateFullscreenButton);

  btnZoomReset.addEventListener("click", () => {
    zoom = 1.0;
    panX = 0;
    panY = 0;
    applyTransform();
  });

  btnRetry.addEventListener("click", connect);

  // Başlat
  fitCanvasToViewport();
  updateFullscreenButton();
  connect();
})();
