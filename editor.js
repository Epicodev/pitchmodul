// ============================================================
// EPICO DECK EDITOR
// In-browser editing — tekst, skjul/slet/tilføj slides, reorder
// State i localStorage, eksport med ændringer
// ============================================================

(function () {
  'use strict';

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  // Unikt deck-ID baseret på klient (fra cover-slide)
  function getDeckId() {
    const coverTitle = document.title || 'pitch';
    return 'epico-deck::' + coverTitle.toLowerCase().replace(/[^a-z0-9]+/g, '-');
  }

  const DECK_ID = getDeckId();

  // ---------- State ----------
  const state = {
    editMode: false,
    sidebarVisible: false,
    activeSlideIdx: 0,
    hiddenSlides: new Set(),
    customSlides: [],   // bruger-tilføjede slides
    edits: {},          // map af slide-id → indre HTML
    slideOrder: [],     // array af slide-id'er i nuværende rækkefølge
    presenting: false,
    presentingIdx: 0,
  };

  // ---------- Persistens ----------
  function loadState() {
    try {
      const raw = localStorage.getItem(DECK_ID);
      if (!raw) return;
      const saved = JSON.parse(raw);
      state.hiddenSlides = new Set(saved.hiddenSlides || []);
      state.edits = saved.edits || {};
      state.customSlides = saved.customSlides || [];
      state.slideOrder = saved.slideOrder || [];
    } catch (e) {
      console.warn('Kunne ikke loade gemt state:', e);
    }
  }

  function saveState() {
    try {
      localStorage.setItem(DECK_ID, JSON.stringify({
        hiddenSlides: Array.from(state.hiddenSlides),
        edits: state.edits,
        customSlides: state.customSlides,
        slideOrder: state.slideOrder,
        savedAt: Date.now(),
      }));
      showSaveIndicator();
    } catch (e) {
      console.error('Kunne ikke gemme:', e);
    }
  }

  function showSaveIndicator() {
    const ind = $('#editor-save-indicator');
    if (!ind) return;
    ind.classList.add('is-saved');
    ind.textContent = 'Gemt';
    clearTimeout(showSaveIndicator._t);
    showSaveIndicator._t = setTimeout(() => {
      ind.classList.remove('is-saved');
      ind.textContent = 'Auto-gemmes';
    }, 1500);
  }

  function showToast(msg) {
    let toast = $('.editor-toast');
    if (!toast) {
      toast = document.createElement('div');
      toast.className = 'editor-toast';
      document.body.appendChild(toast);
    }
    toast.textContent = msg;
    toast.classList.add('is-visible');
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => toast.classList.remove('is-visible'), 2200);
  }

  // ---------- Slide identitet ----------
  function ensureSlideIds() {
    $$('.slide').forEach((s, i) => {
      if (!s.dataset.slideId) s.dataset.slideId = 'slide-' + (i + 1);
      s.style.position = 'relative';
    });
  }

  function getSlideElements() {
    return $$('.slide');
  }

  function getSlideTitle(slide) {
    const tag = slide.querySelector('.section-tag');
    const h1 = slide.querySelector('h1, h2, h3');
    return (tag && tag.textContent.trim()) ||
           (h1 && h1.textContent.trim().substring(0, 40)) ||
           'Slide';
  }

  function getSlideTag(slide) {
    if (slide.classList.contains('slide--dark')) return 'is-dark';
    if (slide.classList.contains('slide--red')) return 'is-red';
    return '';
  }

  // ---------- Apply persisted state ----------
  function applyState() {
    // Skjulte slides
    getSlideElements().forEach(slide => {
      const id = slide.dataset.slideId;
      if (state.hiddenSlides.has(id)) {
        slide.classList.add('is-hidden');
      } else {
        slide.classList.remove('is-hidden');
      }
    });

    // Edits (HTML-substitutions)
    Object.entries(state.edits).forEach(([id, html]) => {
      const slide = document.querySelector(`[data-slide-id="${id}"]`);
      if (slide && html) {
        // Find by inner-id (vi gemmer per editerbart element via dataset.editId)
        Object.entries(html).forEach(([editId, content]) => {
          const el = slide.querySelector(`[data-edit-id="${editId}"]`);
          if (el) el.innerHTML = content;
        });
      }
    });

    // Custom slides — indsæt på position
    state.customSlides.forEach(custom => {
      if (document.querySelector(`[data-slide-id="${custom.id}"]`)) return;  // allerede inde
      const el = createSlideFromTemplate(custom.template, custom.content || {});
      el.dataset.slideId = custom.id;

      const deck = $('.deck');
      const afterEl = custom.afterSlideId
        ? document.querySelector(`[data-slide-id="${custom.afterSlideId}"]`)
        : null;
      if (afterEl) afterEl.after(el);
      else deck.appendChild(el);

      // Re-anvend hidden state for custom slides
      if (state.hiddenSlides.has(custom.id)) el.classList.add('is-hidden');
    });
  }

  // ---------- Toolbar ----------
  function buildToolbar() {
    const tb = document.createElement('div');
    tb.className = 'editor-toolbar';
    tb.id = 'editor-toolbar';
    tb.innerHTML = `
      <div class="brand">
        <div class="e-mark-small"><span></span><span></span><span></span></div>
        <span>Epico Editor</span>
      </div>
      <div class="toolbar-divider"></div>
      <button class="toolbar-btn" id="btn-toggle-edit" title="Tænd/sluk rediger-mode (E)">✏️ Rediger</button>
      <button class="toolbar-btn" id="btn-toggle-sidebar" title="Vis/skjul slide-oversigt (S)">☰ Slides</button>
      <button class="toolbar-btn" id="btn-add-slide" title="Tilføj nyt slide (N)">＋ Nyt slide</button>
      <button class="toolbar-btn toolbar-btn--ghost" id="btn-reset" title="Nulstil alle ændringer">↺ Nulstil</button>
      <div class="save-indicator" id="editor-save-indicator">Auto-gemmes</div>
      <div class="toolbar-spacer"></div>
      <button class="toolbar-btn" id="btn-export-html" title="Download som HTML">↓ HTML</button>
      <button class="toolbar-btn" id="btn-export-pptx" title="Download som PowerPoint">↓ PowerPoint</button>
      <button class="toolbar-btn toolbar-btn--primary" id="btn-present" title="Start præsentation (P)">▶ Præsenter</button>
    `;
    document.body.appendChild(tb);
    requestAnimationFrame(() => tb.classList.add('is-visible'));
  }

  // ---------- Sidebar ----------
  function buildSidebar() {
    const sb = document.createElement('aside');
    sb.className = 'editor-sidebar';
    sb.id = 'editor-sidebar';
    document.body.appendChild(sb);
    rebuildSidebar();
  }

  function rebuildSidebar() {
    const sb = $('#editor-sidebar');
    if (!sb) return;
    sb.innerHTML = '<div class="sidebar-section-label">Slides i deck</div>';

    getSlideElements().forEach((slide, i) => {
      const id = slide.dataset.slideId;
      const isHidden = state.hiddenSlides.has(id);
      const tag = getSlideTag(slide);
      const sectionTag = (slide.querySelector('.section-tag')?.textContent || `Slide ${i+1}`).trim();
      const heading = slide.querySelector('h1, h2, h3, .h-display, .h1, .h2')?.textContent?.trim().substring(0, 50) || sectionTag;

      const thumb = document.createElement('div');
      thumb.className = `thumb ${tag}`;
      if (isHidden) thumb.classList.add('is-hidden');
      thumb.dataset.targetSlide = id;
      thumb.draggable = true;
      thumb.innerHTML = `
        <div class="thumb-preview">
          <div class="thumb-tag">${escapeHtml(sectionTag)}</div>
          <div class="thumb-title">${escapeHtml(heading)}</div>
        </div>
        <div class="thumb-number">${String(i+1).padStart(2,'0')}</div>
        <div class="thumb-actions">
          <button class="thumb-action-btn thumb-action-btn--hide ${isHidden ? 'is-hidden-state' : ''}" data-action="hide" title="Skjul fra præsentation">${isHidden ? '👁' : '⊘'}</button>
          <button class="thumb-action-btn thumb-action-btn--delete" data-action="delete" title="Slet permanent">×</button>
        </div>
      `;

      // Klik på thumb = scroll til slide
      thumb.addEventListener('click', (e) => {
        if (e.target.closest('.thumb-action-btn')) return;
        slide.scrollIntoView({ behavior: 'smooth', block: 'start' });
        $$('.thumb').forEach(t => t.classList.remove('is-active'));
        thumb.classList.add('is-active');
      });

      // Action-buttons
      thumb.querySelector('[data-action="hide"]').addEventListener('click', (e) => {
        e.stopPropagation();
        toggleSlideHidden(id);
      });
      thumb.querySelector('[data-action="delete"]').addEventListener('click', (e) => {
        e.stopPropagation();
        if (confirm('Slet dette slide permanent? (Du kan ikke fortryde — men du kan nulstille hele decket fra toolbar.)')) {
          deleteSlide(id);
        }
      });

      // Drag-and-drop
      setupDragOnThumb(thumb, id);

      sb.appendChild(thumb);

      // "+" tilføj-slide knap mellem thumbs
      if (i < getSlideElements().length - 1) {
        const addBtn = document.createElement('button');
        addBtn.className = 'add-slide-btn';
        addBtn.textContent = '＋ Tilføj slide her';
        addBtn.addEventListener('click', () => openTemplateModal(id));
        sb.appendChild(addBtn);
      }
    });

    // Tilføj-knap til sidst
    const lastAdd = document.createElement('button');
    lastAdd.className = 'add-slide-btn';
    lastAdd.textContent = '＋ Tilføj slide til sidst';
    lastAdd.addEventListener('click', () => openTemplateModal(null));
    sb.appendChild(lastAdd);
  }

  // ---------- Drag-reorder ----------
  let dragSourceId = null;
  function setupDragOnThumb(thumb, slideId) {
    thumb.addEventListener('dragstart', (e) => {
      dragSourceId = slideId;
      thumb.classList.add('is-dragging');
      e.dataTransfer.effectAllowed = 'move';
    });
    thumb.addEventListener('dragend', () => {
      thumb.classList.remove('is-dragging');
      $$('.thumb').forEach(t => t.classList.remove('is-drop-target'));
    });
    thumb.addEventListener('dragover', (e) => {
      e.preventDefault();
      thumb.classList.add('is-drop-target');
    });
    thumb.addEventListener('dragleave', () => {
      thumb.classList.remove('is-drop-target');
    });
    thumb.addEventListener('drop', (e) => {
      e.preventDefault();
      if (!dragSourceId || dragSourceId === slideId) return;
      moveSlideBefore(dragSourceId, slideId);
      dragSourceId = null;
    });
  }

  function moveSlideBefore(sourceId, targetId) {
    const source = document.querySelector(`[data-slide-id="${sourceId}"]`);
    const target = document.querySelector(`[data-slide-id="${targetId}"]`);
    if (!source || !target) return;
    target.before(source);
    rebuildSidebar();
    persistOrder();
    showToast('Rækkefølge ændret');
  }

  function persistOrder() {
    state.slideOrder = getSlideElements().map(s => s.dataset.slideId);
    saveState();
  }

  // ---------- Edit-mode ----------
  function toggleEditMode() {
    state.editMode = !state.editMode;
    document.body.classList.toggle('edit-mode', state.editMode);
    $('#btn-toggle-edit').classList.toggle('is-active', state.editMode);
    if (state.editMode) {
      enableInlineEditing();
      mountSlideEditActions();
      showToast('Rediger-mode tændt — klik på tekst for at ændre');
    } else {
      disableInlineEditing();
      unmountSlideEditActions();
    }
  }

  function makeEditableId(slideEl, el) {
    if (!el.dataset.editId) {
      const i = Array.from(slideEl.querySelectorAll('[data-edit-id]')).length + 1;
      el.dataset.editId = 'e' + i;
    }
    return el.dataset.editId;
  }

  function enableInlineEditing() {
    getSlideElements().forEach(slide => {
      // Editerbare elementer: overskrifter, paragraffer, list items, badges
      const editable = slide.querySelectorAll([
        'h1', 'h2', 'h3', 'h4',
        '.h-display', '.h1', '.h2', '.h3', '.h4',
        'p', 'li',
        '.eyebrow', '.section-tag',
        '.fact-text', '.fact-figure',
        '.research-tile .value', '.research-tile .key', '.research-tile .source',
        '.priority-title', '.priority-desc',
        '.dna-title', '.dna-body',
        '.service-tagline', '.service-bullets li',
        '.service-stat-value', '.service-stat-label',
        '.step-title', '.step-desc', '.step-marker', '.step-when',
        '.case-headline', '.case-block li', '.case-label',
        '.contact-block .name', '.contact-block .title', '.contact-block .reach',
        '.cell',
        '.divider-title',
        '.stat-number', '.stat-label',
        '.footer-value',
      ].join(','));

      editable.forEach(el => {
        if (el.children.length > 1) return;  // Skip elementer med komplekse børn
        makeEditableId(slide, el);
        el.contentEditable = 'true';
        el.spellcheck = false;
        el.addEventListener('blur', onEditBlur);
        el.addEventListener('paste', onEditPaste);
      });
    });
  }

  function disableInlineEditing() {
    $$('[contenteditable="true"]').forEach(el => {
      el.contentEditable = 'false';
      el.removeEventListener('blur', onEditBlur);
      el.removeEventListener('paste', onEditPaste);
    });
  }

  function onEditBlur(e) {
    const el = e.target;
    const slide = el.closest('.slide');
    if (!slide) return;
    const slideId = slide.dataset.slideId;
    const editId = el.dataset.editId;
    if (!slideId || !editId) return;
    if (!state.edits[slideId]) state.edits[slideId] = {};
    state.edits[slideId][editId] = el.innerHTML;
    saveState();
  }

  function onEditPaste(e) {
    // Strip rich-text formatting på paste
    e.preventDefault();
    const text = (e.clipboardData || window.clipboardData).getData('text/plain');
    document.execCommand('insertText', false, text);
  }

  function mountSlideEditActions() {
    getSlideElements().forEach(slide => {
      if (slide.querySelector('.slide-edit-actions')) return;
      const isHidden = state.hiddenSlides.has(slide.dataset.slideId);
      const refineType = getRefineTypeForSlide(slide);

      const actions = document.createElement('div');
      actions.className = 'slide-edit-actions';
      actions.innerHTML = `
        ${refineType ? '<button data-action="refine" class="refine-btn">✦ Skærp</button>' : ''}
        <button data-action="hide" class="${isHidden ? 'is-hidden-state' : ''}">${isHidden ? '👁 Vis igen' : '⊘ Skjul'}</button>
        <button data-action="delete">× Slet</button>
        <button data-action="add-after">＋ Indsæt slide efter</button>
      `;
      slide.appendChild(actions);

      actions.querySelector('[data-action="hide"]').addEventListener('click', () =>
        toggleSlideHidden(slide.dataset.slideId)
      );
      actions.querySelector('[data-action="delete"]').addEventListener('click', () => {
        if (confirm('Slet dette slide permanent?')) deleteSlide(slide.dataset.slideId);
      });
      actions.querySelector('[data-action="add-after"]').addEventListener('click', () =>
        openTemplateModal(slide.dataset.slideId)
      );
      if (refineType) {
        actions.querySelector('[data-action="refine"]').addEventListener('click', () =>
          openRefineModal(slide, refineType)
        );
      }
    });
  }

  // ---------- Skærp slide ----------
  // Identificér hvilke slides der kan skærpes (skal være AI-genereret)
  function getRefineTypeForSlide(slide) {
    const id = slide.dataset.slideId || '';
    const num = parseInt(id.replace('slide-', ''), 10);
    if (num === 4) return 'research_facts';      // Research
    if (num === 5) return 'strategic_priorities'; // Prioriteter
    if (num === 6) return 'value_mappings';       // Mapping
    if (num === 16) return 'case_recommendation'; // Case
    if (num === 17) return 'next_steps';          // Næste skridt
    if (id.startsWith('service-') && !id.includes('-process') && !id.includes('-concepts')) {
      return 'service_slide';
    }
    return null;
  }

  function openRefineModal(slide, refineType) {
    let modal = $('.refine-modal-backdrop');
    if (!modal) {
      modal = document.createElement('div');
      modal.className = 'refine-modal-backdrop';
      modal.innerHTML = `
        <div class="refine-modal">
          <button class="modal-close" id="refine-close">×</button>
          <span class="eyebrow" style="margin-bottom:8px;">Skærp denne slide</span>
          <h2 id="refine-title">Hvordan skal sliden skærpes?</h2>
          <p class="refine-subtitle">Claude regenererer kun denne slide ud fra din direktive. Resten af pitchen er uændret.</p>

          <div class="refine-presets">
            <button class="refine-preset" data-directive="Gør indholdet markant mere konkret — erstat generiske formuleringer med specifikke tal, navne og eksempler.">📊 Mere konkret</button>
            <button class="refine-preset" data-directive="Tilpas tonen til Procurement: TCO, SLA, kontraktvilkår, kommercielle vilkår. Drop strategisk/visionært sprog.">💼 Mere kommerciel</button>
            <button class="refine-preset" data-directive="Løft niveauet til strategisk/executive — forretningsoutcome, vækst-impact, partnerskab. Drop operationelle detaljer.">🎯 Mere strategisk</button>
            <button class="refine-preset" data-directive="Mere teknisk dybde — stack-specifik, senior-erfaring, specifikke teknologier. Drop blød corporate-snak.">⚙️ Mere teknisk</button>
            <button class="refine-preset" data-directive="Mere assertiv og direkte. Drop hedging-ord som 'kan', 'måske', 'typisk'. Stå ved hvad vi gør.">⚡ Mere direkte</button>
            <button class="refine-preset" data-directive="Tilføj mere kunde-specifik kontekst. Brug kundens navn, branche-jargon og deres situation aktivt.">👤 Mere personlig</button>
          </div>

          <label class="field">
            <span class="field-label">Eller skriv din egen direktive</span>
            <textarea id="refine-directive-text" rows="3" placeholder="fx 'fokuser kun på cybersecurity-vinklen og drop andre temaer' eller 'gør den kortere og skarpere'"></textarea>
          </label>

          <div class="refine-actions">
            <button class="btn btn--ghost" id="refine-cancel">Annullér</button>
            <button class="btn btn--primary" id="refine-submit">✦ Skærp slide</button>
          </div>
        </div>
      `;
      document.body.appendChild(modal);
      modal.addEventListener('click', e => { if (e.target === modal) closeRefineModal(); });
      $('#refine-close').addEventListener('click', closeRefineModal);
      $('#refine-cancel').addEventListener('click', closeRefineModal);
      $('#refine-submit').addEventListener('click', submitRefine);
      $$('.refine-preset').forEach(btn => {
        btn.addEventListener('click', () => {
          $('#refine-directive-text').value = btn.dataset.directive;
        });
      });
    }

    modal._targetSlide = slide;
    modal._refineType = refineType;
    $('#refine-directive-text').value = '';
    modal.classList.add('is-visible');
  }

  function closeRefineModal() {
    const modal = $('.refine-modal-backdrop');
    if (modal) modal.classList.remove('is-visible');
  }

  async function submitRefine() {
    const modal = $('.refine-modal-backdrop');
    const slide = modal._targetSlide;
    const refineType = modal._refineType;
    const directive = $('#refine-directive-text').value.trim();

    if (!directive) {
      alert('Vælg en preset eller skriv din egen direktive.');
      return;
    }

    // Indsaml nuværende slide-indhold via DOM-traversal
    const currentContent = extractSlideContent(slide, refineType);
    if (!currentContent) {
      alert('Kunne ikke læse slide-indhold.');
      return;
    }

    const submitBtn = $('#refine-submit');
    submitBtn.disabled = true;
    submitBtn.textContent = '⟳ Claude skærper...';

    try {
      const res = await fetch(`${window.location.origin}/api/refine-slide`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          slide_type: refineType,
          current_content: currentContent,
          directive: directive,
          client_name: extractClientName(),
        }),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Ukendt fejl');
      }

      const data = await res.json();
      const refined = data.refined_content;

      // Anvend det nye indhold på sliden
      applySlideContent(slide, refineType, refined);
      saveState();
      closeRefineModal();
      showToast('Slide skærpet ✦');
    } catch (e) {
      alert(`Skærpning fejlede: ${e.message}`);
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = '✦ Skærp slide';
    }
  }

  function extractClientName() {
    const h1 = document.querySelector('.layout-cover h1');
    return h1 ? h1.textContent.trim().replace(/×.*$/s, '').trim() : 'Kunden';
  }

  function extractSlideContent(slide, refineType) {
    if (refineType === 'research_facts') {
      return Array.from(slide.querySelectorAll('.research-tile')).map(tile => ({
        key: tile.querySelector('.key')?.textContent.trim() || '',
        value: tile.querySelector('.value')?.textContent.trim() || '',
        source: (tile.querySelector('.source')?.textContent.trim() || '').replace(/^Kilde:\s*/, ''),
      }));
    }
    if (refineType === 'strategic_priorities') {
      return Array.from(slide.querySelectorAll('.priority-item')).map(item => ({
        title: item.querySelector('.priority-title')?.textContent.trim() || '',
        description: item.querySelector('.priority-desc')?.textContent.trim() || '',
      }));
    }
    if (refineType === 'value_mappings') {
      return Array.from(slide.querySelectorAll('.mapping .row')).map(row => {
        const cells = row.querySelectorAll('.cell');
        return {
          challenge: cells[0]?.textContent.trim() || '',
          epico_service: '',
          solution: cells[1]?.textContent.trim() || '',
        };
      });
    }
    if (refineType === 'next_steps') {
      return Array.from(slide.querySelectorAll('.step-block')).map(block => ({
        title: block.querySelector('.step-title')?.textContent.trim() || '',
        description: block.querySelector('.step-desc')?.textContent.trim() || '',
        when: block.querySelector('.step-when')?.textContent.trim() || '',
      }));
    }
    if (refineType === 'case_recommendation') {
      const blocks = slide.querySelectorAll('.case-block');
      return {
        headline: slide.querySelector('.h1')?.textContent.trim() || '',
        intro: slide.querySelector('.body-lg')?.textContent.trim() || '',
        what: Array.from(blocks[0]?.querySelectorAll('li') || []).map(li => li.textContent.trim()),
        why: Array.from(blocks[1]?.querySelectorAll('li') || []).map(li => li.textContent.trim()),
        result: Array.from(blocks[2]?.querySelectorAll('li') || []).map(li => li.textContent.trim()),
        value: Array.from(blocks[3]?.querySelectorAll('li') || []).map(li => li.textContent.trim()),
      };
    }
    if (refineType === 'service_slide') {
      return {
        service_name: slide.querySelector('.service-h1')?.textContent.trim().replace(/\.$/, '') || '',
        tagline: slide.querySelector('.service-tagline')?.textContent.trim() || '',
        what_we_deliver: Array.from(slide.querySelectorAll('.service-col:nth-of-type(1) .service-bullets li')).map(li => li.textContent.trim()),
        key_stats: Array.from(slide.querySelectorAll('.service-stat')).map(s => ({
          value: s.querySelector('.service-stat-value')?.textContent.trim() || '',
          label: s.querySelector('.service-stat-label')?.textContent.trim() || '',
        })),
        who_its_for: Array.from(slide.querySelectorAll('.service-col:nth-of-type(3) .service-bullets li')).map(li => li.textContent.trim()),
        typical_roles: slide.querySelectorAll('.footer-row .footer-value')[0]?.textContent.trim() || '',
        relevant_partners: slide.querySelectorAll('.footer-row .footer-value')[1]?.textContent.trim() || '',
      };
    }
    return null;
  }

  function applySlideContent(slide, refineType, refined) {
    if (refineType === 'research_facts' && Array.isArray(refined)) {
      slide.querySelectorAll('.research-tile').forEach((tile, i) => {
        const fact = refined[i];
        if (!fact) return;
        const key = tile.querySelector('.key');
        const value = tile.querySelector('.value');
        const source = tile.querySelector('.source');
        if (key) key.textContent = fact.key || '';
        if (value) value.textContent = fact.value || '';
        if (source) source.textContent = 'Kilde: ' + (fact.source || '');
      });
    }
    else if (refineType === 'strategic_priorities' && Array.isArray(refined)) {
      slide.querySelectorAll('.priority-item').forEach((item, i) => {
        const p = refined[i];
        if (!p) return;
        const title = item.querySelector('.priority-title');
        const desc = item.querySelector('.priority-desc');
        if (title) title.textContent = p.title || '';
        if (desc) desc.textContent = p.description || '';
      });
    }
    else if (refineType === 'value_mappings' && Array.isArray(refined)) {
      slide.querySelectorAll('.mapping .row').forEach((row, i) => {
        const m = refined[i];
        if (!m) return;
        const cells = row.querySelectorAll('.cell');
        if (cells[0]) cells[0].textContent = m.challenge || '';
        if (cells[1]) cells[1].innerHTML = `<strong>${m.epico_service || ''}:</strong> ${m.solution || ''}`;
      });
    }
    else if (refineType === 'next_steps' && Array.isArray(refined)) {
      slide.querySelectorAll('.step-block').forEach((block, i) => {
        const s = refined[i];
        if (!s) return;
        const title = block.querySelector('.step-title');
        const desc = block.querySelector('.step-desc');
        const when = block.querySelector('.step-when');
        if (title) title.textContent = s.title || '';
        if (desc) desc.textContent = s.description || '';
        if (when) when.textContent = s.when || '';
      });
    }
    else if (refineType === 'case_recommendation') {
      const blocks = slide.querySelectorAll('.case-block');
      const headlineEl = slide.querySelector('.h1');
      const introEl = slide.querySelector('.body-lg');
      if (headlineEl && refined.headline) headlineEl.textContent = refined.headline;
      if (introEl && refined.intro) introEl.textContent = refined.intro;
      ['what', 'why', 'result', 'value'].forEach((key, i) => {
        const items = refined[key];
        if (Array.isArray(items) && blocks[i]) {
          const ul = blocks[i].querySelector('ul');
          if (ul) {
            ul.innerHTML = items.map(it => `<li>${it}</li>`).join('');
          }
        }
      });
    }
    else if (refineType === 'service_slide') {
      const taglineEl = slide.querySelector('.service-tagline');
      if (taglineEl && refined.tagline) taglineEl.textContent = refined.tagline;
      const whatBullets = slide.querySelectorAll('.service-col:nth-of-type(1) .service-bullets li');
      (refined.what_we_deliver || []).forEach((b, i) => { if (whatBullets[i]) whatBullets[i].textContent = b; });
      const whoBullets = slide.querySelectorAll('.service-col:nth-of-type(3) .service-bullets li');
      (refined.who_its_for || []).forEach((b, i) => { if (whoBullets[i]) whoBullets[i].textContent = b; });
      const stats = slide.querySelectorAll('.service-stat');
      (refined.key_stats || []).forEach((s, i) => {
        if (stats[i]) {
          const v = stats[i].querySelector('.service-stat-value');
          const l = stats[i].querySelector('.service-stat-label');
          if (v) v.textContent = s.value || '';
          if (l) l.textContent = s.label || '';
        }
      });
    }

    // Gem ændringer i edits state så de overlever reload
    const slideId = slide.dataset.slideId;
    if (!state.edits[slideId]) state.edits[slideId] = {};
    // Save full innerHTML as backup
    state.edits[slideId]['__refined_at'] = String(Date.now());
  }

  function unmountSlideEditActions() {
    $$('.slide-edit-actions').forEach(el => el.remove());
  }

  // ---------- Slide operations ----------
  function toggleSlideHidden(slideId) {
    const slide = document.querySelector(`[data-slide-id="${slideId}"]`);
    if (!slide) return;
    if (state.hiddenSlides.has(slideId)) {
      state.hiddenSlides.delete(slideId);
      slide.classList.remove('is-hidden');
    } else {
      state.hiddenSlides.add(slideId);
      slide.classList.add('is-hidden');
    }
    saveState();
    rebuildSidebar();
    if (state.editMode) {
      unmountSlideEditActions();
      mountSlideEditActions();
    }
    showToast(state.hiddenSlides.has(slideId) ? 'Slide skjult fra præsentation' : 'Slide vises igen');
  }

  function deleteSlide(slideId) {
    const slide = document.querySelector(`[data-slide-id="${slideId}"]`);
    if (!slide) return;
    slide.remove();
    state.hiddenSlides.delete(slideId);
    delete state.edits[slideId];
    state.customSlides = state.customSlides.filter(c => c.id !== slideId);
    persistOrder();
    rebuildSidebar();
    showToast('Slide slettet');
  }

  function resetDeck() {
    if (!confirm('Nulstil alle ændringer (tekst, skjulte slides, tilføjede slides)? Den oprindelige version af decket gendannes.')) return;
    localStorage.removeItem(DECK_ID);
    showToast('Nulstillet — genindlæser...');
    setTimeout(() => location.reload(), 800);
  }

  // ---------- Template-modal ----------
  function openTemplateModal(afterSlideId) {
    let modal = $('.template-modal-backdrop');
    if (!modal) {
      modal = document.createElement('div');
      modal.className = 'template-modal-backdrop';
      modal.innerHTML = `
        <div class="template-modal">
          <button class="modal-close" id="modal-close">×</button>
          <h2>Tilføj et nyt slide</h2>
          <p class="modal-subtitle">Vælg en skabelon. Du kan redigere indholdet bagefter.</p>
          <div class="template-grid" id="template-grid"></div>
        </div>
      `;
      document.body.appendChild(modal);
      modal.addEventListener('click', (e) => {
        if (e.target === modal) modal.classList.remove('is-visible');
      });
      $('#modal-close').addEventListener('click', () => modal.classList.remove('is-visible'));
    }

    // Render templates
    const grid = $('#template-grid');
    grid.innerHTML = '';
    TEMPLATES.forEach(tpl => {
      const card = document.createElement('button');
      card.className = 'template-card';
      card.innerHTML = `
        <div class="template-icon">${tpl.icon}</div>
        <div class="template-name">${tpl.name}</div>
        <div class="template-desc">${tpl.desc}</div>
      `;
      card.addEventListener('click', () => {
        addCustomSlide(tpl.key, afterSlideId);
        modal.classList.remove('is-visible');
      });
      grid.appendChild(card);
    });

    modal.classList.add('is-visible');
  }

  function addCustomSlide(templateKey, afterSlideId) {
    const id = 'custom-' + Date.now() + '-' + Math.floor(Math.random() * 1000);
    const slideEl = createSlideFromTemplate(templateKey, {});
    slideEl.dataset.slideId = id;
    slideEl.style.position = 'relative';

    const afterEl = afterSlideId ? document.querySelector(`[data-slide-id="${afterSlideId}"]`) : null;
    if (afterEl) afterEl.after(slideEl);
    else $('.deck').appendChild(slideEl);

    state.customSlides.push({ id, template: templateKey, afterSlideId, content: {} });
    persistOrder();
    rebuildSidebar();

    // Aktiver edit på det nye slide
    if (state.editMode) {
      // Re-enable editing på det nye slide
      enableInlineEditing();
      mountSlideEditActions();
    }

    slideEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
    showToast('Slide tilføjet — klik på tekst for at redigere');
  }

  // ---------- Slide templates ----------
  const TEMPLATES = [
    {
      key: 'title-body',
      icon: 'H1',
      name: 'Overskrift + brødtekst',
      desc: 'Stor titel og en sammenhængende paragraf. Til intros eller pointer.',
    },
    {
      key: 'three-col-bullets',
      icon: '3⎯',
      name: '3 kolonner med bullets',
      desc: 'Til at fremvise tre relaterede punkter side om side.',
    },
    {
      key: 'stats-hero',
      icon: '#',
      name: 'Stats hero',
      desc: 'Op til 5 store tal med labels — til at fremhæve nøgletal.',
    },
    {
      key: 'quote',
      icon: '“',
      name: 'Citat',
      desc: 'Stort citat med navn og titel under. Til kundereferencer.',
    },
    {
      key: 'section-divider',
      icon: '§',
      name: 'Kapitel-divider',
      desc: 'Mørk fuldskærms-divider med kapitelnummer. Bryder pitchen op.',
    },
    {
      key: 'four-tile',
      icon: '⊞',
      name: '4 tile mosaic',
      desc: 'Fire farve-baggrunde med titel + beskrivelse. Som DNA-sliden.',
    },
    {
      key: 'image-placeholder',
      icon: '◰',
      name: 'Billede + tekst',
      desc: 'Plads til et billede (sælger uploader senere) ved siden af tekst.',
    },
    {
      key: 'contact',
      icon: '@',
      name: 'Kontakt-slide',
      desc: 'Mørk slide med kontakt-info og takkebesked.',
    },
    {
      key: 'blank',
      icon: '◻',
      name: 'Blankt slide',
      desc: 'Tomt slide hvor du selv bygger indholdet op fra bunden.',
    },
  ];

  function createSlideFromTemplate(key, content) {
    const html = renderTemplate(key, content);
    const wrapper = document.createElement('div');
    wrapper.innerHTML = html;
    return wrapper.firstElementChild;
  }

  function renderTemplate(key, c) {
    switch (key) {
      case 'title-body':
        return `<section class="slide custom-slide" data-template="title-body">
          <div class="slide-header"><div class="e-mark-small"><span></span><span></span><span></span></div><div class="wordmark">Epico</div><div class="divider"></div><div class="section-tag">Tilføjet</div></div>
          <div class="layout-full">
            <span class="eyebrow">Eyebrow tekst</span>
            <h2 class="h1" style="max-width:1600px;">Skriv din overskrift her.</h2>
            <p class="body-lg" style="margin-top:32px;max-width:1400px;font-family:var(--font-display);font-weight:500;font-size:28px;line-height:1.4;color:var(--black-currant);letter-spacing:var(--kern-medium);">Skriv din brødtekst her. Brug 2-3 sætninger til at uddybe pointen — hold det skarpt og konkret.</p>
          </div>
          <div class="slide-footer"><span class="footer-mark"></span>Tilføjet slide</div>
        </section>`;

      case 'three-col-bullets':
        return `<section class="slide custom-slide" data-template="three-col-bullets">
          <div class="slide-header"><div class="e-mark-small"><span></span><span></span><span></span></div><div class="wordmark">Epico</div><div class="divider"></div><div class="section-tag">Tilføjet</div></div>
          <div class="layout-full">
            <span class="eyebrow">Eyebrow</span>
            <h2 class="h1" style="max-width:1500px;">Tre relaterede punkter.</h2>
            <div class="dna-grid" style="margin-top:64px;">
              <div class="dna-tile"><div class="dna-num">01</div><div class="dna-title">Første punkt</div><div class="dna-body">Beskrivelse af det første punkt — uddyb gerne med konkrete eksempler.</div></div>
              <div class="dna-tile"><div class="dna-num">02</div><div class="dna-title">Andet punkt</div><div class="dna-body">Beskrivelse af det andet punkt.</div></div>
              <div class="dna-tile"><div class="dna-num">03</div><div class="dna-title">Tredje punkt</div><div class="dna-body">Beskrivelse af det tredje punkt.</div></div>
              <div class="dna-tile"><div class="dna-num">04</div><div class="dna-title">Fjerde punkt</div><div class="dna-body">Beskrivelse af det fjerde punkt (slet hvis ikke nødvendigt).</div></div>
            </div>
          </div>
          <div class="slide-footer"><span class="footer-mark"></span>Tilføjet slide</div>
        </section>`;

      case 'stats-hero':
        return `<section class="slide slide--dark custom-slide" data-template="stats-hero">
          <div class="slide-header"><div class="e-mark-small"><span></span><span></span><span></span></div><div class="wordmark">Epico</div><div class="divider"></div><div class="section-tag">Tilføjet</div></div>
          <div class="layout-full">
            <span class="eyebrow">Eyebrow</span>
            <h2 class="h1" style="color:white;max-width:1600px;">Nøgletal der betyder noget.</h2>
            <div class="stats-hero">
              <div class="stat"><div class="stat-number">+700</div><div class="stat-label">Label 1</div></div>
              <div class="stat"><div class="stat-number">99%</div><div class="stat-label">Label 2</div></div>
              <div class="stat"><div class="stat-number">12</div><div class="stat-label">Label 3</div></div>
              <div class="stat"><div class="stat-number">+500</div><div class="stat-label">Label 4</div></div>
              <div class="stat"><div class="stat-number">2009</div><div class="stat-label">Label 5</div></div>
            </div>
          </div>
          <div class="slide-footer"><span class="footer-mark"></span>Tilføjet slide</div>
        </section>`;

      case 'quote':
        return `<section class="slide slide--dark custom-slide" data-template="quote">
          <div class="slide-header"><div class="e-mark-small"><span></span><span></span><span></span></div><div class="wordmark">Epico</div><div class="divider"></div><div class="section-tag">Citat</div></div>
          <div class="layout-full" style="display:flex;flex-direction:column;justify-content:center;">
            <div style="font-family:var(--font-display);font-weight:700;font-size:160px;color:var(--kiwi);line-height:0.8;letter-spacing:-0.05em;margin-bottom:24px;">"</div>
            <p style="font-family:var(--font-display);font-weight:500;font-size:48px;line-height:1.2;color:white;max-width:1500px;letter-spacing:var(--kern-medium);">Skriv citatet her. Det skal være kort, konkret og bære et budskab der støtter pitchen.</p>
            <div style="margin-top:48px;">
              <div style="font-family:var(--font-display);font-weight:700;font-size:24px;color:var(--kiwi);letter-spacing:var(--kern-medium);">Person Navn</div>
              <div style="font-family:var(--font-body);font-size:16px;color:rgba(255,255,255,0.65);margin-top:6px;">Titel · Virksomhed</div>
            </div>
          </div>
          <div class="slide-footer"><span class="footer-mark"></span>Tilføjet slide</div>
        </section>`;

      case 'section-divider':
        return `<section class="slide slide--dark custom-slide" data-template="section-divider">
          <div class="slide-header"><div class="e-mark-small"><span></span><span></span><span></span></div><div class="wordmark">Epico</div><div class="divider"></div><div class="section-tag">Kapitel</div></div>
          <div class="layout-divider">
            <div class="divider-num">04</div>
            <div class="divider-tag">Kapitel 04</div>
            <h2 class="divider-title">Næste <span class="accent">kapitel.</span></h2>
          </div>
          <div class="slide-footer"><span class="footer-mark"></span>Tilføjet slide</div>
        </section>`;

      case 'four-tile':
        return `<section class="slide custom-slide" data-template="four-tile">
          <div class="slide-header"><div class="e-mark-small"><span></span><span></span><span></span></div><div class="wordmark">Epico</div><div class="divider"></div><div class="section-tag">Tilføjet</div></div>
          <div class="layout-full">
            <span class="eyebrow">Eyebrow</span>
            <h2 class="h1" style="max-width:1500px;">Fire ting <span class="accent">at fremhæve.</span></h2>
            <div class="dna-grid" style="margin-top:64px;">
              <div class="dna-tile"><div class="dna-num">01</div><div class="dna-title">Punkt et</div><div class="dna-body">Kort beskrivelse — 1-2 sætninger.</div></div>
              <div class="dna-tile"><div class="dna-num">02</div><div class="dna-title">Punkt to</div><div class="dna-body">Kort beskrivelse — 1-2 sætninger.</div></div>
              <div class="dna-tile"><div class="dna-num">03</div><div class="dna-title">Punkt tre</div><div class="dna-body">Kort beskrivelse — 1-2 sætninger.</div></div>
              <div class="dna-tile"><div class="dna-num">04</div><div class="dna-title">Punkt fire</div><div class="dna-body">Kort beskrivelse — 1-2 sætninger.</div></div>
            </div>
          </div>
          <div class="slide-footer"><span class="footer-mark"></span>Tilføjet slide</div>
        </section>`;

      case 'image-placeholder':
        return `<section class="slide custom-slide" data-template="image-placeholder">
          <div class="slide-header"><div class="e-mark-small"><span></span><span></span><span></span></div><div class="wordmark">Epico</div><div class="divider"></div><div class="section-tag">Tilføjet</div></div>
          <div class="layout-full" style="display:grid;grid-template-columns:1fr 1fr;gap:80px;align-items:center;">
            <div>
              <span class="eyebrow">Eyebrow</span>
              <h2 class="h1" style="margin-top:16px;">Overskrift der spiller op til billedet.</h2>
              <p class="body-lg" style="margin-top:24px;font-size:20px;">Uddybende tekst — beskriv hvad billedet illustrerer og hvorfor det er relevant.</p>
            </div>
            <div style="background:var(--beige);min-height:600px;display:flex;align-items:center;justify-content:center;font-family:var(--font-body);font-weight:700;font-size:14px;letter-spacing:var(--kern-label);text-transform:uppercase;color:var(--light-grey);">
              [Indsæt billede senere]
            </div>
          </div>
          <div class="slide-footer"><span class="footer-mark"></span>Tilføjet slide</div>
        </section>`;

      case 'contact':
        return `<section class="slide slide--dark custom-slide" data-template="contact">
          <div class="slide-header"><div class="e-mark-small"><span></span><span></span><span></span></div><div class="wordmark">Epico</div><div class="divider"></div><div class="section-tag">Kontakt</div></div>
          <div class="layout-contact">
            <div class="contact-title">
              <span class="eyebrow">Lad os tage næste skridt</span>
              <h2 class="h1" style="color:white;max-width:700px;">Vi glæder os til at <span class="accent">høre fra jer.</span></h2>
              <p class="body-lg" style="color:rgba(255,255,255,0.7);margin-top:32px;max-width:600px;">Spørgsmål eller præciseringer? Skriv eller ring direkte.</p>
            </div>
            <div class="contact-cards">
              <div class="contact-block">
                <div class="role">Kontakt</div>
                <div class="name">Fornavn Efternavn</div>
                <div class="title">Titel · Epico DK</div>
                <div class="reach">T: +45 00 00 00 00<br>M: navn@epico.dk</div>
              </div>
            </div>
          </div>
          <div class="slide-footer"><span class="footer-mark"></span>Tilføjet slide</div>
        </section>`;

      case 'blank':
      default:
        return `<section class="slide custom-slide" data-template="blank">
          <div class="slide-header"><div class="e-mark-small"><span></span><span></span><span></span></div><div class="wordmark">Epico</div><div class="divider"></div><div class="section-tag">Tilføjet</div></div>
          <div class="layout-full">
            <span class="eyebrow">Eyebrow</span>
            <h2 class="h1">Skriv din overskrift.</h2>
            <p class="body-lg" style="margin-top:32px;font-size:24px;">Tilføj indhold her.</p>
          </div>
          <div class="slide-footer"><span class="footer-mark"></span>Tilføjet slide</div>
        </section>`;
    }
  }

  // ---------- Present mode ----------
  function getVisibleSlides() {
    return getSlideElements().filter(s => !s.classList.contains('is-hidden'));
  }

  function updatePresentScale() {
    const scale = Math.min(window.innerWidth / 1920, window.innerHeight / 1080);
    document.documentElement.style.setProperty('--present-scale', scale);
  }

  function showPresentSlide(idx) {
    const visible = getVisibleSlides();
    if (visible.length === 0) return;
    idx = Math.max(0, Math.min(visible.length - 1, idx));
    state.presentingIdx = idx;
    getSlideElements().forEach(s => s.classList.remove('is-present-active'));
    visible[idx].classList.add('is-present-active');
    updateProgressIndicator();
  }

  function updateProgressIndicator() {
    let prog = $('.present-progress');
    if (!prog) {
      prog = document.createElement('div');
      prog.className = 'present-progress';
      document.body.appendChild(prog);
    }
    const visible = getVisibleSlides();
    prog.textContent = `${state.presentingIdx + 1} / ${visible.length}`;
  }

  function startPresentMode() {
    if (state.editMode) toggleEditMode();
    state.presenting = true;
    state.presentingIdx = 0;
    document.body.classList.add('is-presenting');

    // Skjul også eventuel eksisterende deck-nav fra app.js
    const deckNav = document.querySelector('.deck-nav');
    if (deckNav) deckNav.style.display = 'none';

    updatePresentScale();
    showPresentSlide(0);

    // Exit-hint vises i top-right og fader efter 3 sek
    let hint = $('.present-exit-hint');
    if (!hint) {
      hint = document.createElement('div');
      hint.className = 'present-exit-hint';
      hint.textContent = 'ESC for at afslutte · → for næste';
      document.body.appendChild(hint);
    }
    hint.classList.remove('is-faded');
    requestAnimationFrame(() => hint.classList.add('is-faded'));

    // Request fullscreen
    const root = document.documentElement;
    if (root.requestFullscreen) {
      root.requestFullscreen().catch(() => {});
    }

    // Resize handler
    window.addEventListener('resize', updatePresentScale);
  }

  function exitPresentMode() {
    state.presenting = false;
    document.body.classList.remove('is-presenting');
    getSlideElements().forEach(s => s.classList.remove('is-present-active'));

    const deckNav = document.querySelector('.deck-nav');
    if (deckNav) deckNav.style.display = '';

    const hint = $('.present-exit-hint');
    if (hint) hint.remove();

    if (document.fullscreenElement && document.exitFullscreen) {
      document.exitFullscreen().catch(() => {});
    }

    window.removeEventListener('resize', updatePresentScale);
  }

  // Lyt efter fullscreen exit (fx hvis brugeren trykker ESC)
  document.addEventListener('fullscreenchange', () => {
    if (!document.fullscreenElement && state.presenting) {
      exitPresentMode();
    }
  });

  // Klik i present-mode = næste slide (men ikke fra editor-UI eller hjælper-paneler)
  document.addEventListener('click', (e) => {
    if (!state.presenting) return;
    // Ignorér klik fra elementer som ikke er en del af selve slide-canvas'et
    if (e.target.closest('.present-exit-hint, .present-progress, .editor-toolbar, .editor-sidebar, .template-modal-backdrop')) return;
    // Kun fremad-klik hvis vi rammer et slide
    if (!e.target.closest('.slide')) return;
    showPresentSlide(state.presentingIdx + 1);
  });

  // ---------- Eksport ----------
  function exportHtml() {
    // Tag DOM-state, fjern editor-UI, og skab en standalone HTML
    const clone = document.documentElement.cloneNode(true);

    // Fjern editor-toolbar, sidebar, modal, toast, edit-actions
    $$('.editor-toolbar, .editor-sidebar, .template-modal-backdrop, .editor-toast, .slide-edit-actions, .deck-nav', clone).forEach(el => el.remove());

    // Fjern script-tags (editor.js og app.js — vi vil have en ren visning)
    $$('script', clone).forEach(s => s.remove());

    // Fjern body-klasser relateret til edit-mode
    const body = clone.querySelector('body');
    if (body) {
      body.classList.remove('edit-mode', 'sidebar-visible');
    }

    // Fjern contenteditable
    $$('[contenteditable]', clone).forEach(el => el.removeAttribute('contenteditable'));
    $$('[data-edit-id]', clone).forEach(el => el.removeAttribute('data-edit-id'));

    // Fjern is-hidden slides
    $$('.slide.is-hidden', clone).forEach(el => el.remove());

    // Erstat /static/ med relative paths så det virker som standalone
    let html = '<!doctype html>\n' + clone.outerHTML;
    html = html.replace(/href="\/static\/([^"]+)"/g, 'href="$1"')
               .replace(/src="\/static\/([^"]+)"/g, 'src="$1"');

    // Tilføj nav-script kun
    html = html.replace('</body>', '<script src="app.js"></script></body>');

    // Download
    const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const safeName = (document.title || 'epico-pitch').toLowerCase().replace(/[^a-z0-9]+/g, '-');
    a.href = url;
    a.download = `${safeName}-edited.html`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);

    showToast('HTML downloaded');
  }

  async function exportPptx() {
    // PPTX skal genereres af backend ud fra editeret indhold.
    // Vi laver en mini-extract af slide-tekster og sender til /api/generate-deck-pptx-from-html
    // Simplere: vi har ikke en sådan endpoint endnu, så fall back til at fortælle brugeren at PPTX
    // ikke endnu reflekterer in-browser edits.
    showToast('PPTX-eksport med edits er endnu ikke understøttet — brug HTML for nu');
    setTimeout(() => {
      if (confirm('PPTX bruger den oprindelige AI-genererede version (uden in-browser edits). Vil du downloade den nu?')) {
        // Vi har ingen direkte adgang til original analysis-data herfra,
        // så vi linker brugeren tilbage til composer
        const composerUrl = new URL(window.location.href);
        composerUrl.pathname = '/';
        window.open(composerUrl.toString(), '_blank');
      }
    }, 300);
  }

  // ---------- Helpers ----------
  function escapeHtml(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, c => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    }[c]));
  }

  // ---------- Init ----------
  function init() {
    ensureSlideIds();
    loadState();
    applyState();

    buildToolbar();
    buildSidebar();

    // Vis sidebar default
    state.sidebarVisible = true;
    $('#editor-sidebar').classList.add('is-visible');
    document.body.classList.add('sidebar-visible');

    // Toolbar event-handlers
    $('#btn-toggle-edit').addEventListener('click', toggleEditMode);
    $('#btn-toggle-sidebar').addEventListener('click', () => {
      state.sidebarVisible = !state.sidebarVisible;
      $('#editor-sidebar').classList.toggle('is-visible', state.sidebarVisible);
      document.body.classList.toggle('sidebar-visible', state.sidebarVisible);
    });
    $('#btn-add-slide').addEventListener('click', () => openTemplateModal(null));
    $('#btn-reset').addEventListener('click', resetDeck);
    $('#btn-export-html').addEventListener('click', exportHtml);
    $('#btn-export-pptx').addEventListener('click', exportPptx);
    $('#btn-present').addEventListener('click', startPresentMode);

    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
      // Present-mode: pile-taster + ESC har første prioritet
      if (state.presenting) {
        if (e.key === 'ArrowRight' || e.key === ' ' || e.key === 'PageDown') {
          e.preventDefault();
          showPresentSlide(state.presentingIdx + 1);
          return;
        }
        if (e.key === 'ArrowLeft' || e.key === 'PageUp') {
          e.preventDefault();
          showPresentSlide(state.presentingIdx - 1);
          return;
        }
        if (e.key === 'Escape') {
          e.preventDefault();
          exitPresentMode();
          return;
        }
        if (e.key === 'Home') { e.preventDefault(); showPresentSlide(0); return; }
        if (e.key === 'End') { e.preventDefault(); showPresentSlide(getVisibleSlides().length - 1); return; }
        return;  // I present-mode: ignorer alle andre keys
      }

      // Editor shortcuts (kun når ikke editing tekst)
      if (e.target.matches && e.target.matches('[contenteditable="true"]')) return;
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
      if (e.key === 'e' || e.key === 'E') { if (!e.metaKey && !e.ctrlKey) { e.preventDefault(); toggleEditMode(); }}
      if (e.key === 's' || e.key === 'S') { if (!e.metaKey && !e.ctrlKey) { e.preventDefault(); $('#btn-toggle-sidebar').click(); }}
      if (e.key === 'n' || e.key === 'N') { if (!e.metaKey && !e.ctrlKey) { e.preventDefault(); openTemplateModal(null); }}
      if (e.key === 'p' || e.key === 'P') { if (!e.metaKey && !e.ctrlKey) { e.preventDefault(); startPresentMode(); }}
    });

    // Highlight active thumb on scroll
    let scrollTimer = null;
    window.addEventListener('scroll', () => {
      clearTimeout(scrollTimer);
      scrollTimer = setTimeout(() => {
        const slides = getSlideElements();
        const viewportCenter = window.scrollY + window.innerHeight / 2;
        let nearest = null;
        let nearestDist = Infinity;
        slides.forEach(s => {
          const rect = s.getBoundingClientRect();
          const sCenter = window.scrollY + rect.top + rect.height / 2;
          const d = Math.abs(sCenter - viewportCenter);
          if (d < nearestDist) { nearestDist = d; nearest = s; }
        });
        if (nearest) {
          $$('.thumb').forEach(t => t.classList.remove('is-active'));
          const thumb = document.querySelector(`.thumb[data-target-slide="${nearest.dataset.slideId}"]`);
          if (thumb) thumb.classList.add('is-active');
        }
      }, 80);
    });

    console.log('%cEpico Deck Editor', 'font:700 16px sans-serif;color:#690F23;');
    console.log('Tastatur: E=Rediger, S=Slide-oversigt, N=Nyt slide. Edits gemmes automatisk i denne browser.');
  }

  // Vent på at deck er bygget
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
