// ============================================================
// EPICO MASTER PITCH DECK — NAVIGATION
// ============================================================

(function () {
  const deck = document.getElementById('deck');
  const slides = Array.from(deck.querySelectorAll('.slide'));
  const total = slides.length;

  const btnPrev = document.getElementById('btn-prev');
  const btnNext = document.getElementById('btn-next');
  const btnPresent = document.getElementById('btn-present');
  const btnPrint = document.getElementById('btn-print');
  const currentEl = document.getElementById('current-slide');
  const totalEl = document.getElementById('total-slides');

  totalEl.textContent = String(total).padStart(2, '0');

  let currentIdx = 0;
  let presentMode = false;

  function pad(n) { return String(n).padStart(2, '0'); }

  function setActive(idx) {
    currentIdx = Math.max(0, Math.min(total - 1, idx));
    currentEl.textContent = pad(currentIdx + 1);

    if (presentMode) {
      slides.forEach((s, i) => s.classList.toggle('active', i === currentIdx));
    } else {
      slides[currentIdx].scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }

  function next() { setActive(currentIdx + 1); }
  function prev() { setActive(currentIdx - 1); }

  function togglePresent() {
    presentMode = !presentMode;
    deck.classList.toggle('present-mode', presentMode);
    btnPresent.textContent = presentMode ? 'Afslut' : 'Præsenter';

    if (presentMode) {
      // Fit slide to viewport
      const scale = Math.min(
        window.innerWidth / 1920,
        window.innerHeight / 1080
      );
      document.documentElement.style.setProperty('--present-scale', scale);

      slides.forEach((s, i) => s.classList.toggle('active', i === currentIdx));

      if (document.documentElement.requestFullscreen) {
        document.documentElement.requestFullscreen().catch(() => {});
      }
    } else {
      if (document.fullscreenElement && document.exitFullscreen) {
        document.exitFullscreen().catch(() => {});
      }
      slides.forEach(s => s.classList.remove('active'));
      setActive(currentIdx);
    }
  }

  // Genberegn skala når vinduet ændrer størrelse
  window.addEventListener('resize', function () {
    if (presentMode) {
      const scale = Math.min(
        window.innerWidth / 1920,
        window.innerHeight / 1080
      );
      document.documentElement.style.setProperty('--present-scale', scale);
    }
  });

  // ESC ud af præsentationsmode
  document.addEventListener('fullscreenchange', function () {
    if (!document.fullscreenElement && presentMode) {
      presentMode = false;
      deck.classList.remove('present-mode');
      btnPresent.textContent = 'Præsenter';
      slides.forEach(s => s.classList.remove('active'));
    }
  });

  // ---------- Knapper ----------
  btnPrev.addEventListener('click', prev);
  btnNext.addEventListener('click', next);
  btnPresent.addEventListener('click', togglePresent);
  btnPrint.addEventListener('click', function () {
    window.print();
  });

  // ---------- Keyboard ----------
  document.addEventListener('keydown', function (e) {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

    switch (e.key) {
      case 'ArrowRight':
      case 'PageDown':
      case ' ':
        e.preventDefault();
        next();
        break;
      case 'ArrowLeft':
      case 'PageUp':
        e.preventDefault();
        prev();
        break;
      case 'Home':
        e.preventDefault();
        setActive(0);
        break;
      case 'End':
        e.preventDefault();
        setActive(total - 1);
        break;
      case 'p':
      case 'P':
        if (!e.metaKey && !e.ctrlKey) {
          e.preventDefault();
          togglePresent();
        }
        break;
      case 'Escape':
        if (presentMode) togglePresent();
        break;
    }
  });

  // ---------- Scroll tracking (browse-mode) ----------
  let ticking = false;
  window.addEventListener('scroll', function () {
    if (presentMode || ticking) return;
    ticking = true;
    requestAnimationFrame(function () {
      const center = window.scrollY + window.innerHeight / 2;
      let nearest = 0;
      let dist = Infinity;
      slides.forEach((s, i) => {
        const rect = s.getBoundingClientRect();
        const sCenter = window.scrollY + rect.top + rect.height / 2;
        const d = Math.abs(sCenter - center);
        if (d < dist) { dist = d; nearest = i; }
      });
      if (nearest !== currentIdx) {
        currentIdx = nearest;
        currentEl.textContent = pad(currentIdx + 1);
      }
      ticking = false;
    });
  });

  // ---------- Init ----------
  setActive(0);

  console.log('%cEpico Master Pitch Deck', 'font:700 16px sans-serif;color:#690F23;');
  console.log('Tastatur: ← → for at navigere, P for præsentationsmode, Cmd/Ctrl+P for PDF');
})();
