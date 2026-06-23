// ============================================================
// EPICO PITCH COMPOSER — UI logic
// Orkestrer: brief → AI research → review → generate
// ============================================================

const API_BASE = window.location.origin;

const state = {
  brief: null,        // form data
  analysis: null,     // claude output
  deckUrl: null,      // final generated deck
};

// ---------- DOM helpers ----------
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function setActiveTab(name) {
  $$('.tab').forEach(t => t.classList.toggle('is-active', t.dataset.tab === name));
  $$('.tab-panel').forEach(p => p.classList.toggle('is-active', p.dataset.panel === name));
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function enableTab(name) {
  const tab = $(`.tab[data-tab="${name}"]`);
  if (tab) tab.disabled = false;
}

function completeTab(name) {
  const tab = $(`.tab[data-tab="${name}"]`);
  if (tab) tab.classList.add('is-complete');
}

// ---------- Health check ----------
async function checkHealth() {
  const pill = $('#api-status');
  try {
    const res = await fetch(`${API_BASE}/api/health`);
    const data = await res.json();
    if (data.anthropic_key_set) {
      pill.textContent = 'Forbundet · API-key OK';
      pill.classList.add('is-ok');
    } else {
      pill.textContent = 'API-key mangler';
      pill.classList.add('is-warn');
    }
  } catch {
    pill.textContent = 'Backend offline';
    pill.classList.add('is-error');
  }
}

// ---------- CVR lookup ----------
async function lookupCVR() {
  const input = $('input[name="cvr_number"]');
  const nameInput = $('input[name="client_name"]');
  const result = $('#cvr-result');

  const cvrVal = input.value.trim();
  const nameVal = nameInput.value.trim();
  const query = cvrVal || nameVal;
  const type = cvrVal ? 'cvr' : 'name';

  if (!query) {
    result.hidden = false;
    result.classList.add('is-error');
    result.innerHTML = 'Skriv enten CVR-nummer eller kundenavn først.';
    return;
  }

  result.hidden = false;
  result.classList.remove('is-error');
  result.innerHTML = '<em>Søger...</em>';

  try {
    const res = await fetch(`${API_BASE}/api/cvr-lookup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, type }),
    });

    if (!res.ok) {
      result.classList.add('is-error');
      result.innerHTML = `Ingen virksomhed fundet for "<strong>${query}</strong>"`;
      return;
    }

    const { data } = await res.json();
    if (data.cvr && !cvrVal) input.value = data.cvr;
    if (data.name && !nameVal) nameInput.value = data.name;

    result.innerHTML = `
      <div class="cvr-name">${data.name || query}</div>
      <div class="cvr-meta">
        CVR ${data.cvr || '—'} ·
        ${data.industry_desc || '—'} ·
        ${data.employees ? data.employees + ' ansatte' : 'ansatte ukendt'}
        ${data.address ? '<br>' + data.address : ''}
      </div>
    `;
  } catch (e) {
    result.classList.add('is-error');
    result.innerHTML = `Fejl ved opslag: ${e.message}`;
  }
}

// ---------- Upload ----------
function setupUpload() {
  const zone = $('#upload-zone');
  const input = $('#upload-input');
  const selected = $('#upload-selected');
  const prompt = zone.querySelector('.upload-prompt');

  function handle(file) {
    if (!file) return;
    if (file.type !== 'application/pdf') {
      alert('Filen skal være en PDF.');
      return;
    }
    prompt.hidden = true;
    selected.hidden = false;
    selected.innerHTML = `
      <span class="file-icon">PDF</span>
      <span>${file.name} <span style="color:var(--light-grey);font-weight:400;">(${(file.size/1024/1024).toFixed(1)} MB)</span></span>
    `;
  }

  input.addEventListener('change', (e) => handle(e.target.files[0]));

  ['dragenter', 'dragover'].forEach(ev =>
    zone.addEventListener(ev, e => { e.preventDefault(); zone.classList.add('is-dragging'); })
  );
  ['dragleave', 'drop'].forEach(ev =>
    zone.addEventListener(ev, e => { e.preventDefault(); zone.classList.remove('is-dragging'); })
  );
  zone.addEventListener('drop', e => {
    const file = e.dataTransfer.files[0];
    if (file) {
      input.files = e.dataTransfer.files;
      handle(file);
    }
  });
}

// ---------- Step indicator helpers ----------
function setStepActive(step) {
  $$('.status-step').forEach(s => {
    if (s.dataset.step === step) {
      s.classList.remove('is-pending');
      s.classList.add('is-active');
    }
  });
}

function setStepComplete(step) {
  const s = $(`.status-step[data-step="${step}"]`);
  if (s) {
    s.classList.remove('is-active');
    s.classList.add('is-complete');
  }
}

function setStepError(step, msg) {
  const s = $(`.status-step[data-step="${step}"]`);
  if (s) {
    s.classList.remove('is-active', 'is-pending');
    s.classList.add('is-error');
    if (msg) s.querySelector('.step-text').textContent = msg;
  }
}

function resetSteps() {
  $$('.status-step').forEach(s => {
    s.classList.remove('is-active', 'is-complete', 'is-error');
    s.classList.add('is-pending');
  });
}

// ---------- Run AI research ----------
async function runResearch(e) {
  e.preventDefault();

  const form = $('#brief-form');
  const formData = new FormData();

  // Indsaml form-data
  const clientName = form.client_name.value.trim();
  const cvrNumber = form.cvr_number.value.trim();
  const pdfFile = form.annual_report.files[0];

  // Pitch-længde
  const pitchLength = form.querySelector('input[name="pitch_length"]:checked')?.value || 'medium';

  // Lag 1: Sælgers brief (strukturerede inputs)
  const meetingStakeholder = form.querySelector('input[name="meeting_stakeholder"]:checked')?.value || '';
  const meetingStage = form.querySelector('input[name="meeting_stage"]:checked')?.value || 'first_touch';
  const meetingHistory = form.meeting_history.value.trim();
  const personalAngle = form.personal_angle.value.trim();
  const insiderInsights = form.insider_insights.value.trim();
  const exclusions = form.exclusions.value.trim();
  const tone = form.querySelector('input[name="tone"]:checked')?.value || 'balanced';

  // Pitch-vinkel
  const pitchFocus = form.pitch_focus.value.trim();
  const servicesChecked = Array.from(form.querySelectorAll('input[name="services"]:checked')).map(c => c.value);
  const emphasisInput = form.querySelector('input[name="emphasis"]:checked');
  const emphasis = emphasisInput ? emphasisInput.value : '';

  // Lag 2: Slide-for-slide dictation
  const dictWhyMeeting = form.dict_why_meeting.value.trim();
  const dictResearchFacts = form.dict_research_facts.value.trim();
  const dictPriorities = form.dict_priorities.value.trim();
  const dictMappings = form.dict_mappings.value.trim();
  const dictNextSteps = form.dict_next_steps.value.trim();

  // Slide-toggles (hvilke "om Epico"-slides skal med)
  const includedSlides = Array.from(form.querySelectorAll('input[name="slide_includes"]:checked')).map(c => c.value);

  if (!clientName) {
    alert('Kundenavn er påkrævet.');
    return;
  }

  // Gem hele brief'en i state
  state.brief = {
    client_name: clientName,
    cvr_number: cvrNumber,
    pitch_length: pitchLength,
    // Lag 1
    meeting_stakeholder: meetingStakeholder,
    meeting_stage: meetingStage,
    meeting_history: meetingHistory,
    personal_angle: personalAngle,
    insider_insights: insiderInsights,
    exclusions: exclusions,
    tone: tone,
    // Pitch-vinkel
    pitch_focus: pitchFocus,
    services_to_highlight: servicesChecked,
    emphasis: emphasis,
    // Lag 2
    dict_why_meeting: dictWhyMeeting,
    dict_research_facts: dictResearchFacts,
    dict_priorities: dictPriorities,
    dict_mappings: dictMappings,
    dict_next_steps: dictNextSteps,
    included_slides: includedSlides,
    contact_person: form.contact_person.value.trim(),
    city: form.city.value.trim(),
    date: form.date.value,
    team: {
      kam: {
        name: form.kam_name.value.trim(),
        title: form.kam_title.value.trim(),
        phone: form.kam_phone.value.trim(),
        email: form.kam_email.value.trim(),
      },
      rm: {
        name: form.rm_name.value.trim(),
        title: form.rm_title.value.trim(),
        phone: form.rm_phone.value.trim(),
        email: form.rm_email.value.trim(),
      },
    },
  };

  formData.append('client_name', clientName);
  if (cvrNumber) formData.append('cvr_number', cvrNumber);
  formData.append('pitch_length', pitchLength);
  // Lag 1
  if (meetingStakeholder) formData.append('meeting_stakeholder', meetingStakeholder);
  formData.append('meeting_stage', meetingStage);
  if (meetingHistory) formData.append('meeting_history', meetingHistory);
  if (personalAngle) formData.append('personal_angle', personalAngle);
  if (insiderInsights) formData.append('insider_insights', insiderInsights);
  if (exclusions) formData.append('exclusions', exclusions);
  formData.append('tone', tone);
  // Pitch-vinkel
  if (pitchFocus) formData.append('pitch_focus', pitchFocus);
  if (servicesChecked.length) formData.append('services_to_highlight', servicesChecked.join(','));
  if (emphasis) formData.append('emphasis', emphasis);
  // Lag 2
  if (dictWhyMeeting) formData.append('dict_why_meeting', dictWhyMeeting);
  if (dictResearchFacts) formData.append('dict_research_facts', dictResearchFacts);
  if (dictPriorities) formData.append('dict_priorities', dictPriorities);
  if (dictMappings) formData.append('dict_mappings', dictMappings);
  if (dictNextSteps) formData.append('dict_next_steps', dictNextSteps);
  if (includedSlides.length) formData.append('included_slides', includedSlides.join(','));
  if (pdfFile) formData.append('annual_report', pdfFile);

  // Skift til research tab
  enableTab('research');
  setActiveTab('research');
  resetSteps();
  $('#research-summary').hidden = true;

  // Visuel feedback — vis trin sekventielt mens vi venter
  setStepActive('cvr');
  await new Promise(r => setTimeout(r, 400));
  setStepComplete('cvr');
  setStepActive('pdf');
  if (pdfFile) {
    await new Promise(r => setTimeout(r, 600));
  }
  setStepComplete('pdf');
  setStepActive('crawl');
  await new Promise(r => setTimeout(r, 800));
  setStepComplete('crawl');
  setStepActive('websearch');
  await new Promise(r => setTimeout(r, 1200));
  setStepComplete('websearch');
  setStepActive('claude');

  // Kald backend
  try {
    const res = await fetch(`${API_BASE}/api/research`, {
      method: 'POST',
      body: formData,
    });

    if (!res.ok) {
      const err = await res.json();
      setStepError('claude', err.detail || 'Claude-analyse fejlede.');
      return;
    }

    const data = await res.json();
    state.analysis = data.analysis;

    setStepComplete('claude');
    setStepActive('done');
    await new Promise(r => setTimeout(r, 400));
    setStepComplete('done');

    // Vis kort opsummering
    const summary = $('#research-summary');
    summary.hidden = false;
    summary.innerHTML = `
      <h3>${data.client_name}</h3>
      <p class="summary-text">${state.analysis.client_summary || ''}</p>
      <p class="summary-text" style="margin-top:12px;color:var(--light-grey);">
        Branche: <strong style="color:var(--black-currant);">${state.analysis.industry_tag || '—'}</strong>
        ${data.pdf_pages_parsed ? ` · ${data.pdf_pages_parsed} sider læst fra årsrapport` : ''}
        ${data.cvr_data ? ` · CVR ${data.cvr_data.cvr}` : ''}
      </p>
    `;

    // Aktivér review tab
    enableTab('review');
    completeTab('brief');
    completeTab('research');

    // Byg review UI
    buildReviewUI();

    // Auto-skift til review efter 1.5s
    setTimeout(() => setActiveTab('review'), 1500);

  } catch (e) {
    setStepError('claude', `Netværksfejl: ${e.message}`);
  }
}

// ---------- Build review UI ----------
function buildReviewUI() {
  const a = state.analysis;
  const c = $('#review-container');

  const facts = a.research_facts.map((f, i) => `
    <div class="review-item">
      <span class="field-hint">Fakta ${i + 1}</span>
      <div class="review-grid-3">
        <input class="editable" data-path="research_facts.${i}.key" value="${escapeHtml(f.key)}" placeholder="Label">
        <input class="editable" data-path="research_facts.${i}.value" value="${escapeHtml(f.value)}" placeholder="Værdi">
        <input class="editable" data-path="research_facts.${i}.source" value="${escapeHtml(f.source)}" placeholder="Kilde">
      </div>
    </div>
  `).join('');

  const priorities = a.strategic_priorities.map((p, i) => `
    <div class="review-item">
      <span class="field-hint">Prioritet ${i + 1}</span>
      <input class="editable" data-path="strategic_priorities.${i}.title" value="${escapeHtml(p.title)}" placeholder="Titel">
      <textarea class="editable" data-path="strategic_priorities.${i}.description" rows="2" placeholder="Beskrivelse">${escapeHtml(p.description)}</textarea>
    </div>
  `).join('');

  const mappings = a.value_mappings.map((m, i) => `
    <div class="review-item">
      <span class="field-hint">Mapping ${i + 1}</span>
      <textarea class="editable" data-path="value_mappings.${i}.challenge" rows="2" placeholder="Udfordring">${escapeHtml(m.challenge)}</textarea>
      <div class="review-grid-2">
        <input class="editable" data-path="value_mappings.${i}.epico_service" value="${escapeHtml(m.epico_service)}" placeholder="Epico Service">
        <input class="editable" data-path="value_mappings.${i}.solution" value="${escapeHtml(m.solution)}" placeholder="Løsning">
      </div>
    </div>
  `).join('');

  const steps = a.next_steps.map((s, i) => `
    <div class="review-item">
      <span class="field-hint">Skridt ${i + 1}</span>
      <div class="review-grid-2">
        <input class="editable" data-path="next_steps.${i}.title" value="${escapeHtml(s.title)}" placeholder="Titel">
        <input class="editable" data-path="next_steps.${i}.when" value="${escapeHtml(s.when)}" placeholder="Tidsramme">
      </div>
      <textarea class="editable" data-path="next_steps.${i}.description" rows="2" placeholder="Beskrivelse">${escapeHtml(s.description)}</textarea>
    </div>
  `).join('');

  const caseRec = a.case_recommendation;
  const caseBlock = `
    <div class="review-item">
      <span class="field-hint">Case-overskrift</span>
      <input class="editable" data-path="case_recommendation.headline" value="${escapeHtml(caseRec.headline)}">
    </div>
    <div class="review-item">
      <span class="field-hint">Intro</span>
      <textarea class="editable" data-path="case_recommendation.intro" rows="2">${escapeHtml(caseRec.intro)}</textarea>
    </div>
    ${['what', 'why', 'result', 'value'].map(col => `
      <div class="review-item">
        <span class="field-hint">${col === 'what' ? 'Hvad' : col === 'why' ? 'Hvorfor' : col === 'result' ? 'Resultat' : 'Værdi'}</span>
        ${caseRec[col].map((item, i) => `
          <input class="editable" data-path="case_recommendation.${col}.${i}" value="${escapeHtml(item)}">
        `).join('')}
      </div>
    `).join('')}
  `;

  c.innerHTML = `
    <div class="review-block">
      <div class="review-block-head">
        <h3>Research-fakta om ${escapeHtml(state.brief.client_name)}</h3>
        <span class="slide-ref">Slide 04</span>
      </div>
      ${facts}
    </div>

    <div class="review-block">
      <div class="review-block-head">
        <h3>Strategiske prioriteter</h3>
        <span class="slide-ref">Slide 05</span>
      </div>
      ${priorities}
    </div>

    <div class="review-block">
      <div class="review-block-head">
        <h3>Udfordring → løsning mapping</h3>
        <span class="slide-ref">Slide 06</span>
      </div>
      ${mappings}
    </div>

    <div class="review-block">
      <div class="review-block-head">
        <h3>Relevant case</h3>
        <span class="slide-ref">Slide 16 · Branche: ${escapeHtml(a.industry_tag)}</span>
      </div>
      ${caseBlock}
    </div>

    <div class="review-block">
      <div class="review-block-head">
        <h3>Næste skridt</h3>
        <span class="slide-ref">Slide 17</span>
      </div>
      ${steps}
    </div>
  `;

  // Bind edits — opdater state.analysis live
  $$('.editable[data-path]').forEach(el => {
    el.addEventListener('input', (e) => {
      const path = e.target.dataset.path.split('.');
      let obj = state.analysis;
      for (let i = 0; i < path.length - 1; i++) {
        const key = path[i];
        obj = obj[isNaN(key) ? key : parseInt(key)];
      }
      const lastKey = path[path.length - 1];
      obj[isNaN(lastKey) ? lastKey : parseInt(lastKey)] = e.target.value;
    });
  });
}

// ---------- Generate deck ----------
async function generateDeck() {
  const btn = $('#generate-deck-btn');
  btn.disabled = true;
  btn.innerHTML = 'Genererer... <span class="arrow">⟳</span>';

  try {
    const res = await fetch(`${API_BASE}/api/generate-deck`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        client_name: state.brief.client_name,
        analysis: state.analysis,
        meeting: {
          date: state.brief.date,
          city: state.brief.city,
          contact_person: state.brief.contact_person,
        },
        team: state.brief.team,
        included_slides: state.brief.included_slides,
      }),
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const data = await res.json();
    state.deckUrl = data.url;

    $('#open-deck-link').href = data.url;
    enableTab('generate');
    completeTab('review');
    setActiveTab('generate');

  } catch (e) {
    alert(`Generering fejlede: ${e.message}`);
  } finally {
    btn.disabled = false;
    btn.innerHTML = 'Generer deck <span class="arrow">→</span>';
  }
}

// ---------- Download ----------
async function downloadDeck() {
  if (!state.deckUrl) return;
  const a = document.createElement('a');
  a.href = state.deckUrl;
  a.download = `epico-pitch-${state.brief.client_name.toLowerCase().replace(/\s+/g, '-')}.html`;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

async function downloadPptx() {
  const btn = $('#download-pptx-btn');
  if (!btn || !state.analysis) return;

  const originalContent = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<div class="generated-icon">⟳</div><div><div class="generated-title">Genererer PowerPoint...</div><div class="generated-desc">Tager 2-3 sekunder</div></div>';

  try {
    const res = await fetch(`${API_BASE}/api/generate-deck-pptx`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        client_name: state.brief.client_name,
        analysis: state.analysis,
        meeting: {
          date: state.brief.date,
          city: state.brief.city,
          contact_person: state.brief.contact_person,
        },
        team: state.brief.team,
        included_slides: state.brief.included_slides,
      }),
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `epico-pitch-${state.brief.client_name.toLowerCase().replace(/\s+/g, '-')}.pptx`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (e) {
    alert(`PPTX-eksport fejlede: ${e.message}`);
  } finally {
    btn.disabled = false;
    btn.innerHTML = originalContent;
  }
}

// ---------- Utility ----------
function escapeHtml(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ---------- Init ----------
document.addEventListener('DOMContentLoaded', () => {
  checkHealth();
  setupUpload();

  $('#brief-form').addEventListener('submit', runResearch);
  $('#cvr-lookup-btn').addEventListener('click', lookupCVR);
  $('#back-to-brief').addEventListener('click', () => setActiveTab('brief'));
  $('#generate-deck-btn').addEventListener('click', generateDeck);
  $('#download-deck-btn').addEventListener('click', downloadDeck);
  const pptxBtn = $('#download-pptx-btn');
  if (pptxBtn) pptxBtn.addEventListener('click', downloadPptx);
  $('#restart-btn').addEventListener('click', () => location.reload());

  // Tab clicks (kun for completed tabs)
  $$('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      if (tab.disabled) return;
      setActiveTab(tab.dataset.tab);
    });
  });

  // Pitch-længde preset → auto-toggle slides
  const PITCH_LENGTH_PRESETS = {
    short: ['case_study'],
    medium: ['epico_intro_chapter', 'epico_stats', 'epico_dna', 'services_chapter', 'services_overview', 'epic_process', 'case_study'],
    long: ['epico_intro_chapter', 'epico_stats', 'it_market', 'epico_dna', 'services_chapter', 'services_overview', 'competences', 'epic_process', 'case_study'],
  };
  $$('input[name="pitch_length"]').forEach(radio => {
    radio.addEventListener('change', (e) => {
      const preset = PITCH_LENGTH_PRESETS[e.target.value] || PITCH_LENGTH_PRESETS.medium;
      $$('input[name="slide_includes"]').forEach(cb => {
        cb.checked = preset.includes(cb.value);
      });
    });
  });

  // Collapse toggle for slide-dictation
  const dictToggle = $('#dictation-toggle');
  const dictFields = $('#dictation-fields');
  if (dictToggle && dictFields) {
    dictToggle.addEventListener('click', () => {
      const isOpen = !dictFields.hidden;
      dictFields.hidden = isOpen;
      dictToggle.textContent = isOpen ? 'Vis felter ↓' : 'Skjul felter ↑';
      dictToggle.classList.toggle('is-expanded', !isOpen);
    });
  }

  // Sæt dato til i dag som default
  const dateInput = $('input[name="date"]');
  if (dateInput) dateInput.value = new Date().toISOString().split('T')[0];

  // Sæt by til København som default
  const cityInput = $('input[name="city"]');
  if (cityInput && !cityInput.value) cityInput.value = 'København';
});
