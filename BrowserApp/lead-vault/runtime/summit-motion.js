(function () {
  "use strict";

  var root = document.documentElement;
  var reduceQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  var mobileQuery = window.matchMedia("(max-width: 767px)");
  var rafPending = false;
  var parallaxItems = [];
  var stickyItems = [];
  var spotlightItems = [];
  var waterItems = [];

  root.classList.add("summit-motion-js");

  function reducedMotion() {
    return reduceQuery.matches;
  }

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  function parseDelay(value) {
    var parsed = Number.parseInt(String(value || ""), 10);
    if (!Number.isFinite(parsed)) {
      return 0;
    }
    return clamp(parsed, 0, 600);
  }

  function parseSpeed(value) {
    var parsed = Number.parseFloat(String(value || ""));
    if (!Number.isFinite(parsed)) {
      return 0.12;
    }
    return clamp(parsed, 0.05, 0.25);
  }

  function parseClamp(value) {
    var parsed = Number.parseInt(String(value || ""), 10);
    if (!Number.isFinite(parsed)) {
      return 80;
    }
    return clamp(parsed, 16, 180);
  }

  function parseCount(value, fallback) {
    var parsed = Number.parseInt(String(value || ""), 10);
    if (!Number.isFinite(parsed)) {
      return fallback;
    }
    return clamp(parsed, 36, 160);
  }

  function thresholdFromValue(value, fallback) {
    var text = String(value || "").trim();
    if (!text) {
      return fallback;
    }
    if (/^[.#\[]/.test(text)) {
      var target = document.querySelector(text);
      if (target) {
        var rect = target.getBoundingClientRect();
        return window.scrollY + rect.top + rect.height;
      }
      return fallback;
    }
    if (text.endsWith("vh")) {
      return window.innerHeight * (Number.parseFloat(text) / 100);
    }
    if (text.endsWith("%")) {
      return window.innerHeight * (Number.parseFloat(text) / 100);
    }
    if (text.endsWith("px")) {
      return Number.parseFloat(text);
    }
    var parsed = Number.parseFloat(text);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function markReducedMotion() {
    root.classList.toggle("summit-reduced-motion", reducedMotion());
  }

  function setupRevealUp() {
    var items = Array.prototype.slice.call(
      document.querySelectorAll('[data-motion="reveal-up"]')
    );

    if (!items.length) {
      return;
    }

    if (reducedMotion() || !("IntersectionObserver" in window)) {
      items.forEach(function (item) {
        item.classList.add("summit-motion-visible");
      });
      return;
    }

    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) {
            return;
          }
          entry.target.classList.add("summit-motion-visible");
          if (entry.target.dataset.motionOnce !== "false") {
            observer.unobserve(entry.target);
          }
        });
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.12 }
    );

    items.forEach(function (item) {
      var delay = parseDelay(item.getAttribute("data-motion-delay"));
      if (delay) {
        item.style.transitionDelay = delay + "ms";
      }
      observer.observe(item);
    });
  }

  function setupStickyCta() {
    stickyItems = Array.prototype.slice.call(
      document.querySelectorAll('[data-motion="sticky-cta"]')
    );
    updateStickyCta();
  }

  function updateStickyCta() {
    if (!stickyItems.length) {
      return;
    }
    stickyItems.forEach(function (item) {
      var threshold = thresholdFromValue(
        item.getAttribute("data-sticky-after"),
        window.innerHeight * 0.45
      );
      item.classList.toggle("summit-motion-stuck", window.scrollY > threshold);
    });
  }

  function setupParallax() {
    parallaxItems = Array.prototype.slice.call(
      document.querySelectorAll("[data-parallax]")
    );
    updateParallax();
  }

  function updateParallax() {
    if (!parallaxItems.length) {
      return;
    }
    if (reducedMotion() || mobileQuery.matches) {
      parallaxItems.forEach(function (item) {
        item.style.removeProperty("--summit-parallax-x");
        item.style.removeProperty("--summit-parallax-y");
      });
      return;
    }

    var viewportMid = window.innerHeight / 2;
    parallaxItems.forEach(function (item) {
      var rect = item.getBoundingClientRect();
      if (rect.bottom < -120 || rect.top > window.innerHeight + 120) {
        return;
      }
      var speed = parseSpeed(item.getAttribute("data-parallax"));
      var maxTravel = parseClamp(item.getAttribute("data-parallax-clamp"));
      var axis = String(item.getAttribute("data-parallax-axis") || "y").toLowerCase();
      var offset = clamp((viewportMid - (rect.top + rect.height / 2)) * speed, -maxTravel, maxTravel);
      if (axis === "x") {
        item.style.setProperty("--summit-parallax-x", offset.toFixed(1) + "px");
        item.style.setProperty("--summit-parallax-y", "0px");
      } else {
        item.style.setProperty("--summit-parallax-x", "0px");
        item.style.setProperty("--summit-parallax-y", offset.toFixed(1) + "px");
      }
    });
  }

  function setupSpotlight() {
    spotlightItems = Array.prototype.slice.call(
      document.querySelectorAll('[data-bg="cursor-spotlight"]')
    );
    if (!spotlightItems.length || reducedMotion() || mobileQuery.matches) {
      return;
    }
    spotlightItems.forEach(function (item) {
      item.addEventListener(
        "pointermove",
        function (event) {
          var rect = item.getBoundingClientRect();
          var x = ((event.clientX - rect.left) / Math.max(rect.width, 1)) * 100;
          var y = ((event.clientY - rect.top) / Math.max(rect.height, 1)) * 100;
          item.style.setProperty("--summit-spotlight-x", clamp(x, 0, 100).toFixed(2) + "%");
          item.style.setProperty("--summit-spotlight-y", clamp(y, 0, 100).toFixed(2) + "%");
        },
        { passive: true }
      );
    });
  }

  function setupWaterAttractor() {
    waterItems.forEach(function (item) {
      if (item.stop) {
        item.stop();
      }
    });
    waterItems = [];

    var hosts = Array.prototype.slice.call(
      document.querySelectorAll('[data-bg="water-attractor"]')
    );
    if (!hosts.length) {
      return;
    }

    hosts.forEach(function (host) {
      waterItems.push(createWaterAttractor(host));
    });
  }

  function createWaterAttractor(host) {
    var canvas = Array.prototype.slice.call(host.children).find(function (child) {
      return child.classList && child.classList.contains("summit-water-canvas");
    });
    if (!canvas) {
      canvas = document.createElement("canvas");
      canvas.className = "summit-water-canvas";
      canvas.setAttribute("aria-hidden", "true");
      host.insertBefore(canvas, host.firstChild);
    }

    var ctx = canvas.getContext("2d", { alpha: true });
    if (!ctx) {
      return { stop: function () {} };
    }

    var particles = [];
    var waves = [];
    var width = 1;
    var height = 1;
    var dpr = 1;
    var raf = 0;
    var last = window.performance ? window.performance.now() : Date.now();
    var pointer = { x: 0, y: 0, active: false };
    var disabled = reducedMotion();
    var desiredCount = parseCount(host.getAttribute("data-water-particles"), mobileQuery.matches ? 54 : 96);

    function colorVar(name, fallback) {
      return getComputedStyle(host).getPropertyValue(name).trim() || fallback;
    }

    function resize() {
      var rect = host.getBoundingClientRect();
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = Math.max(1, rect.width);
      height = Math.max(1, rect.height);
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      canvas.style.width = width + "px";
      canvas.style.height = height + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      seed();
      drawStatic();
    }

    function seed() {
      particles = [];
      var count = disabled ? Math.min(28, desiredCount) : desiredCount;
      for (var i = 0; i < count; i += 1) {
        particles.push({
          x: Math.random() * width,
          y: Math.random() * height,
          vx: (Math.random() - 0.5) * 0.26,
          vy: (Math.random() - 0.5) * 0.26,
          r: 1.2 + Math.random() * 2.8,
          phase: Math.random() * Math.PI * 2
        });
      }
    }

    function setPointer(event) {
      var rect = host.getBoundingClientRect();
      pointer.x = event.clientX - rect.left;
      pointer.y = event.clientY - rect.top;
      pointer.active = true;
      waves.push({ x: pointer.x, y: pointer.y, r: 2, a: 0.22 });
      if (waves.length > 8) {
        waves.shift();
      }
    }

    function clearPointer() {
      pointer.active = false;
    }

    function paintBackground() {
      var accent = colorVar("--summit-water-accent", "rgba(56, 189, 248, 0.34)");
      var depth = colorVar("--summit-water-depth", "rgba(14, 116, 144, 0.26)");
      ctx.clearRect(0, 0, width, height);
      var gradient = ctx.createLinearGradient(0, 0, width, height);
      gradient.addColorStop(0, depth);
      gradient.addColorStop(0.48, "rgba(255, 255, 255, 0.03)");
      gradient.addColorStop(1, accent);
      ctx.fillStyle = gradient;
      ctx.fillRect(0, 0, width, height);
    }

    function drawStatic() {
      paintBackground();
      particles.forEach(function (p) {
        ctx.beginPath();
        ctx.fillStyle = colorVar("--summit-water-foam", "rgba(224, 247, 255, 0.48)");
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fill();
      });
    }

    function step(now) {
      if (disabled) {
        drawStatic();
        return;
      }

      var dt = clamp((now - last) / 16.67, 0.4, 2);
      last = now;
      paintBackground();

      var foam = colorVar("--summit-water-foam", "rgba(224, 247, 255, 0.56)");
      var accent = colorVar("--summit-water-accent", "rgba(56, 189, 248, 0.34)");
      particles.forEach(function (p) {
        var pullX = pointer.x - p.x;
        var pullY = pointer.y - p.y;
        var distanceSq = pullX * pullX + pullY * pullY;
        if (pointer.active && distanceSq < 52000) {
          var force = (1 - distanceSq / 52000) * 0.16;
          p.vx += pullX * force * 0.004 * dt;
          p.vy += pullY * force * 0.004 * dt;
        }

        p.phase += 0.012 * dt;
        p.vx += Math.cos(p.phase) * 0.006 * dt;
        p.vy += Math.sin(p.phase * 0.8) * 0.006 * dt;
        p.vx *= 0.982;
        p.vy *= 0.982;
        p.x += p.vx * dt;
        p.y += p.vy * dt;

        if (p.x < -20) p.x = width + 20;
        if (p.x > width + 20) p.x = -20;
        if (p.y < -20) p.y = height + 20;
        if (p.y > height + 20) p.y = -20;

        ctx.beginPath();
        ctx.fillStyle = foam;
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fill();
      });

      waves = waves.filter(function (wave) {
        wave.r += 11 * dt;
        wave.a *= 0.93;
        if (wave.a < 0.015) {
          return false;
        }
        ctx.beginPath();
        ctx.strokeStyle = accent.replace(/[\d.]+\)$/, wave.a.toFixed(3) + ")");
        ctx.lineWidth = 1.25;
        ctx.arc(wave.x, wave.y, wave.r, 0, Math.PI * 2);
        ctx.stroke();
        return true;
      });

      raf = window.requestAnimationFrame(step);
    }

    function start() {
      window.cancelAnimationFrame(raf);
      if (!disabled) {
        raf = window.requestAnimationFrame(function (time) {
          last = time;
          step(time);
        });
      }
    }

    resize();
    start();
    host.addEventListener("pointermove", setPointer, { passive: true });
    host.addEventListener("pointerleave", clearPointer, { passive: true });
    window.addEventListener("resize", resize, { passive: true });

    return {
      stop: function () {
        window.cancelAnimationFrame(raf);
        host.removeEventListener("pointermove", setPointer);
        host.removeEventListener("pointerleave", clearPointer);
        window.removeEventListener("resize", resize);
      }
    };
  }

  function requestUpdate() {
    if (rafPending) {
      return;
    }
    rafPending = true;
    window.requestAnimationFrame(function () {
      rafPending = false;
      updateStickyCta();
      updateParallax();
    });
  }

  function refresh() {
    markReducedMotion();
    setupRevealUp();
    setupStickyCta();
    setupParallax();
    setupSpotlight();
    setupWaterAttractor();
    requestUpdate();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", refresh, { once: true });
  } else {
    refresh();
  }

  window.addEventListener("scroll", requestUpdate, { passive: true });
  window.addEventListener("resize", requestUpdate, { passive: true });

  if (typeof reduceQuery.addEventListener === "function") {
    reduceQuery.addEventListener("change", refresh);
  }
  if (typeof mobileQuery.addEventListener === "function") {
    mobileQuery.addEventListener("change", requestUpdate);
  }

  window.SummitMotionRuntime = {
    version: 2,
    refresh: refresh,
    update: requestUpdate
  };
})();
