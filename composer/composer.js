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
      // 503 = registret er nede eller kvoten opbrugt. Det er ikke det samme
      // som at kunden ikke findes, og kræver en anden handling af sælgeren.
      const body = await res.json().catch(() => ({}));
      result.classList.add('is-error');
      result.innerHTML = body.detail
        ? escapeHtml(body.detail)
        : `Ingen virksomhed fundet for "<strong>${escapeHtml(query)}</strong>"`;
      return;
    }

    const { data } = await res.json();
    if (data.cvr && !cvrVal) input.value = data.cvr;
    if (data.name && !nameVal) nameInput.value = data.name;
    updateBriefQuestionsBtn();

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

// ---------- Delte brief-felter ----------
// Både /api/research og /api/brief-questions skal have præcis de samme værdier.
function readSharedBriefFields(form) {
  return {
    client_name: form.client_name.value.trim(),
    cvr_number: form.cvr_number.value.trim(),
    pitch_length: form.querySelector('input[name="pitch_length"]:checked')?.value || 'medium',
    meeting_stakeholder: form.querySelector('input[name="meeting_stakeholder"]:checked')?.value || '',
    meeting_stage: form.querySelector('input[name="meeting_stage"]:checked')?.value || 'first_touch',
    meeting_history: form.meeting_history.value.trim(),
    personal_angle: form.personal_angle.value.trim(),
    insider_insights: form.insider_insights.value.trim(),
    exclusions: form.exclusions.value.trim(),
    pitch_focus: form.pitch_focus.value.trim(),
    services_to_highlight: Array.from(form.querySelectorAll('input[name="services"]:checked')).map(c => c.value),
  };
}

function appendSharedBriefFields(formData, v) {
  formData.append('client_name', v.client_name);
  if (v.cvr_number) formData.append('cvr_number', v.cvr_number);
  formData.append('pitch_length', v.pitch_length);
  if (v.meeting_stakeholder) formData.append('meeting_stakeholder', v.meeting_stakeholder);
  formData.append('meeting_stage', v.meeting_stage);
  if (v.meeting_history) formData.append('meeting_history', v.meeting_history);
  if (v.personal_angle) formData.append('personal_angle', v.personal_angle);
  if (v.insider_insights) formData.append('insider_insights', v.insider_insights);
  if (v.exclusions) formData.append('exclusions', v.exclusions);
  if (v.pitch_focus) formData.append('pitch_focus', v.pitch_focus);
  if (v.services_to_highlight.length) formData.append('services_to_highlight', v.services_to_highlight.join(','));
}

// ---------- Omvendt brief — lad AI stille spørgsmålene ----------
const BRIEF_FIELD_LABELS = {
  insider_insights: 'Konkurrent-situation & insider',
  personal_angle: 'Stakeholder & personlig vinkel',
  meeting_history: 'Mødehistorik',
  pitch_focus: 'Hvad skal pitchen fokusere på?',
  exclusions: 'Eksklusioner',
};

const briefQuestions = {
  items: [],        // spørgsmål fra AI
  answers: {},      // spørgsmåls-index → sælgers svar
  baselines: {},    // feltnavn → feltets tekst før AI-svarene blev føjet på
  syncing: false,   // sandt mens vi selv skriver i et brief-felt
  round: 0,         // hvor mange runder AI'en har kørt (næste kald = round + 1)
  enough: false,    // AI'en har meldt enough_context
  unlocked: false,  // research-knappen er åbnet (af AI'en eller ved spring over)
};

function briefFieldEl(name) {
  return $(`#brief-form [name="${name}"]`);
}

// Alle svar der hører til ét brief-felt, i spørgsmåls-rækkefølge
function briefAnswerTail(field) {
  return briefQuestions.items
    .map((q, i) => (q.field === field ? (briefQuestions.answers[i] || '').trim() : ''))
    .filter(Boolean)
    .join('\n');
}

// Føj svarene TIL feltet — aldrig overskriv sælgers egen tekst
function syncBriefField(field) {
  const el = briefFieldEl(field);
  if (!el) return;
  const base = (briefQuestions.baselines[field] || '').replace(/\s+$/, '');
  const tail = briefAnswerTail(field);
  briefQuestions.syncing = true;
  el.value = base && tail ? `${base}\n${tail}` : (base || tail);
  briefQuestions.syncing = false;
}

// Retter sælger selv i brief-feltet, skal deres tekst vinde
function handleManualBriefEdit(field) {
  if (briefQuestions.syncing) return;
  if (!briefQuestions.items.some(q => q.field === field)) return;

  const el = briefFieldEl(field);
  if (!el) return;
  const tail = briefAnswerTail(field);

  if (tail && el.value.endsWith(tail)) {
    // Kun teksten over svarene er rettet — flyt baseline med
    briefQuestions.baselines[field] = el.value.slice(0, el.value.length - tail.length);
    return;
  }

  // Sælger har redigeret i selve svarene — lad feltet stå og tøm svarboksene
  briefQuestions.baselines[field] = el.value;
  briefQuestions.items.forEach((q, i) => {
    if (q.field !== field) return;
    briefQuestions.answers[i] = '';
    const ta = $(`#brief-questions-body textarea[data-qidx="${i}"]`);
    if (ta) ta.value = '';
  });
}

function updateBriefQuestionsBtn() {
  const input = $('#brief-form [name="client_name"]');
  if (!input) return;
  const ready = input.value.trim().length > 0;
  [$('#brief-questions-btn'), $('#brief-questions-more-btn')].forEach(btn => {
    if (!btn) return;
    btn.disabled = !ready;
    btn.title = ready ? '' : 'Udfyld kundenavn først';
  });
}

// Første runde bor i knappen øverst; opfølgninger i knappen under kortene,
// så sælger aldrig ser to knapper der gør det samme. Har AI'en meldt at den
// har nok, forsvinder begge — så er samtalen slut og research er næste skridt.
function updateBriefQuestionsUi() {
  const hasCards = briefQuestions.items.length > 0;
  const done = briefQuestions.enough;
  const askBtn = $('#brief-questions-btn');
  const more = $('#brief-questions-more');
  const skip = $('#brief-questions-skip');
  const title = $('#brief-questions-head .brief-questions-title');
  const sub = $('#brief-questions-head .brief-questions-sub');

  if (askBtn) askBtn.hidden = hasCards || done;
  if (more) more.hidden = !hasCards || done;
  // Vejen udenom skal kun stå der så længe den kan bruges til noget
  if (skip) skip.hidden = briefQuestions.unlocked;

  if (done && title) title.textContent = 'Vi er igennem spørgsmålene.';
  if (done && sub) {
    sub.textContent = 'Dine svar står i briefen — du kan se og rette dem under Avanceret.';
  } else if (hasCards && title) {
    title.textContent = 'Svar på det du kan.';
  }
  if (!done && hasCards && sub) {
    sub.textContent = 'Spring gerne et spørgsmål over. Alt du skriver havner i briefen — du kan se og rette det under Avanceret.';
  }
  updateBriefQuestionsBtn();
}

// Research-knappen er lukket indtil AI'en har sagt god for briefen — eller
// indtil sælgeren aktivt vælger den fra. Én gang åben forbliver den åben:
// retter han bagefter i felterne, skal han ikke igennem spørgsmålene igen.
function unlockResearch(reason) {
  const btn = $('#run-analysis-btn');
  const note = $('#run-analysis-note');
  briefQuestions.unlocked = true;

  if (btn) {
    btn.disabled = false;
    btn.title = '';
  }
  if (note) {
    note.textContent = reason === 'skipped'
      ? 'Du sprang spørgsmålene over. Research kører på det du selv har skrevet — tjek slide-vælgeren ovenfor før du trykker.'
      : 'AI\'en har nok om mødet. Tjek slide-vælgeren ovenfor, og kør så research.';
    note.classList.add('is-unlocked');
  }
  const skip = $('#brief-questions-skip');
  if (skip) skip.hidden = true;
}

// AI'en er færdig med at spørge: kortene bliver stående i DOM'en (så svarene
// og append-logikken er urørte), men foldes væk bag afslutningen.
function renderBriefQuestionsDone(data) {
  briefQuestions.enough = true;

  const body = $('#brief-questions-body');
  const done = $('#brief-questions-done');
  const text = $('#brief-questions-done-text');
  const slides = $('#brief-questions-done-slides');

  if (body) body.hidden = true;
  if (text) {
    text.textContent = data.assessment
      ? String(data.assessment)
      : 'Jeg har det jeg skal bruge for at bygge et deck der er lavet til denne kunde.';
  }
  if (slides) {
    const reason = (data.recommendation_reason || '').trim();
    slides.hidden = !reason;
    slides.textContent = reason;
  }
  if (done) done.hidden = false;

  unlockResearch('enough');
  updateBriefQuestionsUi();
}

// Sælger skal kunne se at svarene faktisk landede et sted
function markAdvancedUpdated() {
  const note = $('#advanced-note');
  if (note) note.hidden = false;
}

function briefQuestionsMessage(html, append) {
  const body = $('#brief-questions-body');
  if (!body) return;
  body.hidden = false;
  if (append) body.insertAdjacentHTML('beforeend', html);
  else body.innerHTML = html;
}

function clearBriefQuestionsLoading() {
  const loader = $('#brief-questions-loading');
  if (loader) loader.remove();
}

// append = true når sælger beder om flere spørgsmål: nye kort lægges under
// de gamle, og de allerede afgivne svar bliver stående.
function renderBriefQuestions(data, append = false) {
  const body = $('#brief-questions-body');
  if (!body) return;

  const items = Array.isArray(data.questions)
    ? data.questions.filter(q => q && q.question && BRIEF_FIELD_LABELS[q.field])
    : [];

  if (!append) {
    briefQuestions.items = [];
    briefQuestions.answers = {};
    briefQuestions.baselines = {};
  }

  // Nye kort fortsætter nummereringen, så data-qidx og items følges ad
  const offset = briefQuestions.items.length;
  briefQuestions.items = briefQuestions.items.concat(items);

  // Et felt der allerede har en baseline beholder den — ellers ville feltets
  // nuværende tekst (baseline + tidligere svar) blive den nye baseline,
  // og svarene ville stå to gange.
  items.forEach(q => {
    if (briefQuestions.baselines[q.field] === undefined) {
      const el = briefFieldEl(q.field);
      briefQuestions.baselines[q.field] = el ? el.value : '';
    }
  });

  body.hidden = false;

  if (!items.length) {
    briefQuestionsMessage(
      `<div class="brief-questions-error">AI'en havde ingen spørgsmål denne gang. Prøv igen når du har skrevet lidt mere.</div>`,
      append,
    );
    updateBriefQuestionsUi();
    return;
  }

  const html = `
    <div class="brief-question-round">
      ${data.assessment ? `<p class="brief-assessment">${escapeHtml(data.assessment)}</p>` : ''}
      <div class="brief-question-list">
        ${items.map((q, i) => `
          <div class="brief-question">
            <div class="brief-question-q">${escapeHtml(q.question)}</div>
            ${q.why ? `<div class="brief-question-why">${escapeHtml(q.why)}</div>` : ''}
            <textarea class="editable brief-question-answer" data-qidx="${offset + i}" rows="2"
                      placeholder="${escapeHtml(q.example_answer || 'Skriv dit svar her...')}"></textarea>
            <div class="brief-question-target">Føjes til <strong>${escapeHtml(BRIEF_FIELD_LABELS[q.field])}</strong></div>
          </div>
        `).join('')}
      </div>
    </div>
  `;

  if (append) body.insertAdjacentHTML('beforeend', html);
  else body.innerHTML = html;

  // Bind kun de nye svarfelter — de gamle har allerede en lytter
  body.querySelectorAll('.brief-question-answer:not([data-bound])').forEach(ta => {
    ta.dataset.bound = '1';
    ta.addEventListener('input', () => {
      const i = parseInt(ta.dataset.qidx, 10);
      const item = briefQuestions.items[i];
      if (!item) return;
      briefQuestions.answers[i] = ta.value;
      syncBriefField(item.field);
      markAdvancedUpdated();
    });
  });

  updateBriefQuestionsUi();
}

async function askBriefQuestions(append = false) {
  const form = $('#brief-form');
  const btn = append ? $('#brief-questions-more-btn') : $('#brief-questions-btn');
  const body = $('#brief-questions-body');
  if (!form || !btn || !body) return;

  const shared = readSharedBriefFields(form);
  if (!shared.client_name) {
    updateBriefQuestionsBtn();
    return;
  }

  const originalLabel = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = 'Læser din brief... <span class="arrow">⟳</span>';
  briefQuestionsMessage(
    `<div class="brief-questions-loading" id="brief-questions-loading">AI'en læser det du har skrevet og finder de spørgsmål der rykker mest — det tager ca. 5 sekunder.</div>`,
    append,
  );

  const formData = new FormData();
  appendSharedBriefFields(formData, shared);
  // Backend'en tvinger enough_context i tredje runde, så den skal vide hvor
  // langt vi er. Tælleren rykker først når kaldet er lykkedes.
  const roundNumber = briefQuestions.round + 1;
  formData.append('round_number', String(roundNumber));

  try {
    const res = await fetch(`${API_BASE}/api/brief-questions`, {
      method: 'POST',
      body: formData,
    });

    if (!res.ok) {
      let detail = `Kaldet fejlede (HTTP ${res.status}).`;
      try {
        const err = await res.json();
        if (err && err.detail) detail = err.detail;
      } catch { /* ikke JSON — behold standardbesked */ }
      clearBriefQuestionsLoading();
      briefQuestionsMessage(`<div class="brief-questions-error">${escapeHtml(detail)}</div>`, append);
      return;
    }

    const data = await res.json();
    briefQuestions.round = roundNumber;
    clearBriefQuestionsLoading();

    if (data.enough_context) {
      // AI'en er færdig: den sætter fluebenene i vælgeren og åbner research
      renderBriefQuestionsDone(data);
      await applyRecommendedSlides(data.recommended_slide_ids, data.recommendation_reason);
      return;
    }

    renderBriefQuestions(data, append);
  } catch (e) {
    clearBriefQuestionsLoading();
    briefQuestionsMessage(`<div class="brief-questions-error">Netværksfejl: ${escapeHtml(e.message)}</div>`, append);
  } finally {
    btn.disabled = false;
    btn.innerHTML = originalLabel;
    updateBriefQuestionsUi();
  }
}

// ---------- Dit Epico-team (samme værdier hver gang — så husk dem) ----------
const TEAM_STORAGE_KEY = 'epico-composer-team';
const TEAM_FIELDS = [
  'kam_name', 'kam_title', 'kam_phone', 'kam_email',
  'rm_name', 'rm_title', 'rm_phone', 'rm_email',
];

function teamFieldEl(name) {
  return $(`#brief-form [name="${name}"]`);
}

function teamValue(name) {
  const el = teamFieldEl(name);
  return el ? el.value.trim() : '';
}

function loadTeam() {
  let saved;
  try {
    saved = JSON.parse(localStorage.getItem(TEAM_STORAGE_KEY) || '{}');
  } catch {
    return; // korrupt eller blokeret storage — kør bare videre med tomme felter
  }
  if (!saved || typeof saved !== 'object') return;
  TEAM_FIELDS.forEach(name => {
    const el = teamFieldEl(name);
    if (el && typeof saved[name] === 'string' && saved[name].trim()) el.value = saved[name];
  });
}

function saveTeam() {
  const data = {};
  TEAM_FIELDS.forEach(name => {
    const el = teamFieldEl(name);
    if (el) data[name] = el.value;
  });
  try {
    localStorage.setItem(TEAM_STORAGE_KEY, JSON.stringify(data));
  } catch { /* privat browsing eller fuld storage — ikke kritisk */ }
}

function renderTeamSummary() {
  const summary = $('#team-summary');
  const fields = $('#team-fields');
  if (!summary || !fields) return;

  const open = !fields.hidden;
  const kam = teamValue('kam_name');
  const rm = teamValue('rm_name');
  const action = open ? 'Skjul ↑' : 'Redigér';

  if (!kam && !rm) {
    summary.innerHTML = open
      ? `<span class="team-summary-line">Udfyld navn på KAM og RM — de huskes til næste gang</span>
         <span class="team-summary-action">${action}</span>`
      : `<span class="team-summary-line team-summary-line--empty">Udfyld dit team <span class="arrow">→</span></span>`;
    return;
  }

  summary.innerHTML = `
    <span class="team-summary-line">
      <span class="team-summary-role">KAM:</span> ${escapeHtml(kam || '—')}
      <span class="team-summary-dot">·</span>
      <span class="team-summary-role">RM:</span> ${escapeHtml(rm || '—')}
    </span>
    <span class="team-summary-action">${action}</span>
  `;
}

function setupTeam() {
  const summary = $('#team-summary');
  const fields = $('#team-fields');
  if (!summary || !fields) return;

  loadTeam();
  renderTeamSummary();

  summary.addEventListener('click', () => {
    fields.hidden = !fields.hidden;
    renderTeamSummary();
  });

  TEAM_FIELDS.forEach(name => {
    const el = teamFieldEl(name);
    if (!el) return;
    el.addEventListener('input', () => {
      saveTeam();
      renderTeamSummary();
    });
  });
}

// ---------- Run AI research ----------
async function runResearch(e) {
  e.preventDefault();

  // Enter i et tekstfelt kan submitte formularen uden om den låste knap
  if (!briefQuestions.unlocked) {
    const block = $('#brief-questions-block');
    if (block) block.scrollIntoView({ behavior: 'smooth', block: 'center' });
    return;
  }

  const form = $('#brief-form');
  const formData = new FormData();

  // Indsaml form-data
  const shared = readSharedBriefFields(form);
  const clientName = shared.client_name;
  const cvrNumber = shared.cvr_number;
  const pdfFile = form.annual_report.files[0];

  // Pitch-længde
  const pitchLength = shared.pitch_length;

  // Lag 1: Sælgers brief (strukturerede inputs)
  const meetingStakeholder = shared.meeting_stakeholder;
  const meetingStage = shared.meeting_stage;
  const meetingHistory = shared.meeting_history;
  const personalAngle = shared.personal_angle;
  const insiderInsights = shared.insider_insights;
  const exclusions = shared.exclusions;

  // Pitch-vinkel
  const pitchFocus = shared.pitch_focus;
  const servicesChecked = shared.services_to_highlight;

  // Lag 2: Slide-for-slide dictation
  const dictResearchFacts = form.dict_research_facts.value.trim();
  const dictPriorities = form.dict_priorities.value.trim();
  const dictMappings = form.dict_mappings.value.trim();
  const dictNextSteps = form.dict_next_steps.value.trim();

  // Slides sælger har fravalgt — i live-planen og i review-listen
  const excludedSlideIds = currentExcludedSlideIds();

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
    // Pitch-vinkel
    pitch_focus: pitchFocus,
    services_to_highlight: servicesChecked,
    // Lag 2
    dict_research_facts: dictResearchFacts,
    dict_priorities: dictPriorities,
    dict_mappings: dictMappings,
    dict_next_steps: dictNextSteps,
    excluded_slide_ids: excludedSlideIds,
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

  // Klient + Lag 1 + pitch-vinkel (samme felter som /api/brief-questions)
  appendSharedBriefFields(formData, shared);
  // Lag 2
  if (dictResearchFacts) formData.append('dict_research_facts', dictResearchFacts);
  if (dictPriorities) formData.append('dict_priorities', dictPriorities);
  if (dictMappings) formData.append('dict_mappings', dictMappings);
  if (dictNextSteps) formData.append('dict_next_steps', dictNextSteps);
  if (pdfFile) formData.append('annual_report', pdfFile);

  // AI'en skal vide hvilke master-slides der følger efter kundeslidesne, så den
  // kan pege på dem i stedet for at genforklare dem. Uden det skriver den i
  // blinde og gentager fx hele Freelance-argumentet tre slides før jeres egen
  // Freelance-slide siger det samme.
  const picked = currentSelectedSlideIds();
  if (picked && picked.length) formData.append('selected_slide_ids', picked.join(','));

  // Skift til research tab
  enableTab('research');
  setActiveTab('research');
  resetSteps();
  $('#research-summary').hidden = true;

  setStepActive('cvr');

  // Kørslen tager 4-5 minutter, så backend'en svarer med et job-id og arbejder
  // videre bagefter. Tidligere holdt vi HTTP-forbindelsen åben hele vejen, og
  // Railways proxy skar den over ved 300 sekunder — sælgeren mistede kørslen få
  // sekunder før den var færdig. Trinnene nedenfor er nu ægte fremdrift fra
  // serveren, ikke en animation der gætter.
  let data;
  try {
    const res = await fetch(`${API_BASE}/api/research`, {
      method: 'POST',
      body: formData,
    });

    if (!res.ok) {
      setStepError('claude', await readError(res));
      return;
    }

    const { job_id } = await res.json();
    data = await pollResearch(job_id);
    if (!data) return;   // pollResearch har allerede vist fejlen
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
      <p class="summary-text" style="color:var(--light-grey);">
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
    // Her fanges kun rigtige netværksfejl — svar med fejlkode håndteres ovenfor
    setStepError('claude', 'Forbindelsen til serveren blev afbrudt. '
      + 'Tager analysen over et par minutter, kan den blive lukket ned undervejs — '
      + 'prøv en kortere pitch-længde.');
  }
}

// Vores backend svarer med JSON, men proxyer imellem gør ikke. Railway sender
// fx "upstream error" som ren tekst når et kald tager for lang tid, og et
// res.json() på det gav sælgeren "Unexpected token 'u'" i stedet for en besked
// han kan handle på.
async function readError(res) {
  let body = '';
  try { body = (await res.text()).trim(); } catch { /* forbindelsen er væk */ }

  try {
    const parsed = JSON.parse(body);
    if (parsed && parsed.detail) return String(parsed.detail);
  } catch { /* ikke JSON — så er det en proxy der svarer */ }

  if (res.status === 502 || res.status === 503 || res.status === 504 || /upstream|timeout|gateway/i.test(body)) {
    return 'Analysen tog for lang tid, og forbindelsen blev afbrudt undervejs. '
         + 'Prøv med en kortere pitch-længde, eller slå web-søgning fra under Avanceret.';
  }
  if (res.status === 413) return 'Årsrapporten er for stor til at blive sendt. Prøv en mindre PDF.';
  if (res.status === 429) return 'For mange kald lige nu. Vent et halvt minut og prøv igen.';

  return body.slice(0, 200) || `Serveren svarede ${res.status}.`;
}

// Følg en research-kørsel til dørs. Returnerer resultatet, eller null hvis
// noget gik galt (fejlen er så allerede vist på det rigtige trin).
async function pollResearch(jobId) {
  const STEPS = ['cvr', 'pdf', 'crawl', 'websearch', 'claude', 'done'];
  const DEADLINE_MS = 15 * 60 * 1000;   // rigeligt; kørslen tager 4-5 min
  const started = Date.now();
  let shown = new Set();
  let misses = 0;

  while (Date.now() - started < DEADLINE_MS) {
    await new Promise(r => setTimeout(r, 3000));

    let job;
    try {
      const res = await fetch(`${API_BASE}/api/research/${encodeURIComponent(jobId)}`);
      if (res.status === 404) {
        setStepError('claude', 'Kørslen findes ikke længere — serveren er formentlig '
          + 'genstartet undervejs. Kør research igen.');
        return null;
      }
      if (!res.ok) throw new Error(await readError(res));
      job = await res.json();
      misses = 0;
    } catch (e) {
      // Et enkelt mislykket opslag er ikke værd at afbryde en 5-minutters kørsel for
      if (++misses < 5) continue;
      setStepError('claude', 'Mistede forbindelsen til serveren undervejs. '
        + 'Kørslen er muligvis stadig i gang — prøv igen om lidt.');
      return null;
    }

    (job.done_steps || []).forEach(st => {
      if (!shown.has(st)) { setStepComplete(st); shown.add(st); }
    });
    if (job.step && !shown.has(job.step)) setStepActive(job.step);

    if (job.status === 'done') {
      STEPS.forEach(st => { if (!shown.has(st)) { setStepComplete(st); shown.add(st); } });
      return job.result;
    }
    if (job.status === 'error') {
      setStepError(job.step || 'claude', job.detail || 'Analysen fejlede.');
      return null;
    }
  }

  setStepError('claude', 'Kørslen tog usædvanlig lang tid og blev opgivet. Prøv igen, '
    + 'eller vælg en kortere pitch-længde.');
  return null;
}

// ---------- Dækningsrapport (hvordan briefen blev brugt) ----------
function coverageMarkup(cov) {
  if (!cov || typeof cov !== 'object') return '';

  const usage = Array.isArray(cov.brief_usage) ? cov.brief_usage.filter(Boolean) : [];
  const dropped = Array.isArray(cov.dropped) ? cov.dropped.filter(Boolean) : [];
  const missing = Array.isArray(cov.missing_input) ? cov.missing_input.filter(Boolean) : [];
  const weakest = cov.weakest_slide && typeof cov.weakest_slide === 'object' ? cov.weakest_slide : null;

  if (!usage.length && !dropped.length && !missing.length && !weakest) return '';

  const weakestHtml = weakest ? `
    <div class="coverage-warning">
      <span class="coverage-warning-tag">Svageste slide</span>
      <div class="coverage-warning-slide">${escapeHtml(weakest.slide)}</div>
      <p class="coverage-warning-why">${escapeHtml(weakest.why)}</p>
      ${weakest.what_would_fix_it ? `
        <div class="coverage-fix">
          <span class="coverage-fix-label">Sådan løfter du det</span>
          ${escapeHtml(weakest.what_would_fix_it)}
        </div>` : ''}
    </div>
  ` : '';

  const usageHtml = usage.length ? `
    <div class="coverage-section">
      <div class="coverage-section-head">Det her landede i pitchen</div>
      <div class="coverage-list">
        ${usage.map(u => `
          <div class="coverage-item">
            <div class="coverage-input">${escapeHtml(u.input)}</div>
            <div class="coverage-landed">${escapeHtml(u.landed_in)}</div>
            <div class="coverage-how">${escapeHtml(u.how)}</div>
          </div>
        `).join('')}
      </div>
    </div>
  ` : '';

  const droppedHtml = dropped.length ? `
    <div class="coverage-section coverage-section--dropped">
      <div class="coverage-section-head">Det her kom ikke med</div>
      <p class="coverage-section-sub">Er noget af det vigtigt for dig? Skriv det tydeligere i briefen og kør research igen.</p>
      <div class="coverage-list">
        ${dropped.map(d => `
          <div class="coverage-item coverage-item--dropped">
            <div class="coverage-input">${escapeHtml(d.input)}</div>
            <div class="coverage-how">${escapeHtml(d.why)}</div>
          </div>
        `).join('')}
      </div>
    </div>
  ` : '';

  const missingHtml = missing.length ? `
    <div class="coverage-section">
      <div class="coverage-section-head">Det ville jeg gerne have vidst</div>
      <ul class="coverage-missing">
        ${missing.map(m => `<li>${escapeHtml(m)}</li>`).join('')}
      </ul>
    </div>
  ` : '';

  return `
    <div class="review-block coverage-block">
      <div class="review-block-head">
        <h3>Sådan brugte jeg din brief</h3>
        <button type="button" class="collapse-btn is-expanded" id="coverage-toggle">Skjul ↑</button>
      </div>
      <div class="coverage-body" id="coverage-body">
        ${weakestHtml}
        ${usageHtml}
        ${droppedHtml}
        ${missingHtml}
      </div>
    </div>
  `;
}

// ---------- Research-fakta med bytte-funktion ----------
function factsMarkup() {
  const a = state.analysis;
  const facts = Array.isArray(a.research_facts) ? a.research_facts : [];
  const alts = Array.isArray(a.research_facts_alternates) ? a.research_facts_alternates : [];

  return facts.map((f, i) => `
    <div class="review-item fact-item">
      <div class="fact-head">
        <span class="field-hint">Fakta ${i + 1}</span>
        ${alts.length ? `<button type="button" class="fact-swap-btn" data-swap="${i}">Byt ↔</button>` : ''}
      </div>
      <div class="review-grid-3">
        <input class="editable" data-path="research_facts.${i}.key" value="${escapeHtml(f.key)}" placeholder="Label">
        <input class="editable" data-path="research_facts.${i}.value" value="${escapeHtml(f.value)}" placeholder="Værdi">
        <input class="editable" data-path="research_facts.${i}.source" value="${escapeHtml(f.source)}" placeholder="Kilde">
      </div>
      ${f.why_it_matters ? `
        <div class="fact-why">
          <span class="fact-why-label">Intern note</span>${escapeHtml(f.why_it_matters)}
        </div>` : ''}
      ${alts.length ? `
        <div class="fact-alternates" data-alts="${i}" hidden>
          <div class="fact-alt-head">Byt ud med et af disse — den nuværende ryger tilbage i puljen</div>
          <div class="fact-alt-list">
            ${alts.map((alt, j) => `
              <button type="button" class="fact-alt" data-fact="${i}" data-alt="${j}">
                <span class="fact-alt-key">${escapeHtml(alt.key)}</span>
                <span class="fact-alt-value">${escapeHtml(alt.value)}</span>
                <span class="fact-alt-source">Kilde: ${escapeHtml(alt.source)}</span>
                ${alt.why_it_matters ? `<span class="fact-alt-why">${escapeHtml(alt.why_it_matters)}</span>` : ''}
              </button>
            `).join('')}
          </div>
        </div>` : ''}
    </div>
  `).join('');
}

function swapFact(factIndex, altIndex) {
  const a = state.analysis;
  const facts = a.research_facts;
  const alts = a.research_facts_alternates;
  if (!Array.isArray(facts) || !Array.isArray(alts)) return;
  if (!facts[factIndex] || !alts[altIndex]) return;

  // Byt de to — den valgte fakta ryger i puljen, så byttet kan fortrydes
  const chosen = alts[altIndex];
  alts[altIndex] = facts[factIndex];
  facts[factIndex] = chosen;

  renderFacts();
}

function renderFacts() {
  const host = $('#facts-list');
  if (!host) return;

  host.innerHTML = factsMarkup();
  bindEditables(host);

  host.querySelectorAll('.fact-swap-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const panel = host.querySelector(`.fact-alternates[data-alts="${btn.dataset.swap}"]`);
      if (!panel) return;
      const willOpen = panel.hidden;
      host.querySelectorAll('.fact-alternates').forEach(p => { p.hidden = true; });
      host.querySelectorAll('.fact-swap-btn').forEach(b => b.classList.remove('is-open'));
      panel.hidden = !willOpen;
      btn.classList.toggle('is-open', willOpen);
    });
  });

  host.querySelectorAll('.fact-alt').forEach(btn => {
    btn.addEventListener('click', () => {
      swapFact(parseInt(btn.dataset.fact, 10), parseInt(btn.dataset.alt, 10));
    });
  });
}

// Bind edits — opdater state.analysis live
function bindEditables(root) {
  root.querySelectorAll('.editable[data-path]').forEach(el => {
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

// ---------- Slides i det færdige deck (review-fanen) ----------
// Master-slides fravælges gennem slideOverrides — præcis som i brief-fanens
// vælger. AI-kundeslides har ikke et flueben nogen steder, så de samles her og
// rejser med i excluded_slide_ids.
const clientSlideExclusions = new Set();

// Master-slides fjernet HERFRA bliver stående som overstreget linje, så et
// fejlklik kan fortrydes uden at sælger skal tilbage til brief-fanen.
const deckRemovedMasterIds = new Set();

// Backend'ens plan navngiver kundeslidesne, men leverer ikke altid et id.
// Titlerne er faste, så vi kan oversætte dem til de id'er deck-generatoren
// kender — og bruger slidens eget id når det er der.
const CLIENT_SLIDE_ID_RULES = [
  [/titel|cover|forside/i, 'cover'],
  [/research/i, 'research'],
  [/prioritet/i, 'priorities'],
  [/udfordring|løsning|mapping/i, 'mapping'],
  [/case/i, 'case'],
  [/næste skridt/i, 'next-steps'],
  [/kontakt/i, 'contact'],
  [/afslut|outro/i, 'outro'],
];

// Forsiden og afslutningen bærer decket — dem må sælger ikke kunne skrælle af
const FIXED_CLIENT_SLIDE_IDS = new Set(['cover', 'outro', 'closing', 'afslutning']);

// Slide-planen lister case blandt de indledende kundeslides, men decket tegner
// den efter master-slidesne. Listen skal vise deckets rækkefølge, ikke planens.
const CLIENT_SLIDES_AFTER_LIBRARY = new Set([
  'case', 'next-steps', 'contact', 'outro', 'closing', 'afslutning',
]);

function clientSlideId(slide) {
  if (slide && slide.id) return String(slide.id);
  const title = (slide && slide.title) || '';
  const rule = CLIENT_SLIDE_ID_RULES.find(([re]) => re.test(title));
  if (rule) return rule[1];
  return title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'slide';
}

function deckSlideRows() {
  const plan = _planForPreview;
  if (!plan) return [];

  const isOn = s => (s.id in slideOverrides) ? slideOverrides[s.id] : s.default_on;
  const library = plan.library_slides || [];

  // Er en fjernet master-slide tilvalgt igen i brief-fanen, skal linjen
  // ikke blive ved med at hænge her
  deckRemovedMasterIds.forEach(id => {
    const s = library.find(x => x.id === id);
    if (!s || isOn(s)) deckRemovedMasterIds.delete(id);
  });

  const clientRow = (s) => {
    const id = clientSlideId(s);
    return {
      id,
      title: s.title || id,
      kind: 'client',
      fixed: FIXED_CLIENT_SLIDE_IDS.has(id),
      removed: clientSlideExclusions.has(id),
    };
  };

  const masterRows = library
    .filter(s => isOn(s) || deckRemovedMasterIds.has(s.id))
    .map(s => ({ id: s.id, title: s.title, kind: 'library', fixed: false, removed: !isOn(s) }));

  const clientRows = [...(plan.client_slides || []), ...(plan.closing_slides || [])].map(clientRow);
  const before = clientRows.filter(r => !CLIENT_SLIDES_AFTER_LIBRARY.has(r.id));
  const after = clientRows.filter(r => CLIENT_SLIDES_AFTER_LIBRARY.has(r.id));

  // Kontakt-sliden står ikke i planen, men kommer med i decket så snart
  // sælgeren har udfyldt et navn i sit team
  const team = (state.brief && state.brief.team) || {};
  const hasTeam = !!((team.kam || {}).name || (team.rm || {}).name);
  if (hasTeam && !after.some(r => r.id === 'contact')) {
    const outroAt = after.findIndex(r => FIXED_CLIENT_SLIDE_IDS.has(r.id));
    const contact = {
      id: 'contact', title: 'Kontakt', kind: 'client',
      fixed: false, removed: clientSlideExclusions.has('contact'),
    };
    if (outroAt === -1) after.push(contact);
    else after.splice(outroAt, 0, contact);
  }

  return [...before, ...masterRows, ...after];
}

function deckListMarkup() {
  return `
    <div class="review-block deck-list-block">
      <div class="review-block-head">
        <h3>Slides i det færdige deck</h3>
        <span class="slide-ref"><span id="deck-list-count">—</span> slides</span>
      </div>
      <p class="deck-list-intro">
        Rækkefølgen er deckets. Fjern det du ikke skal bruge — ændringen slår igennem
        næste gang du genererer decket.
      </p>
      <div class="deck-list" id="deck-list"></div>
    </div>
  `;
}

function renderDeckSlideList() {
  const host = $('#deck-list');
  if (!host) return;

  const rows = deckSlideRows();
  if (!rows.length) {
    host.innerHTML = `<div class="slide-plan-loading">Slide-planen er ikke indlæst.</div>`;
    return;
  }

  let n = 0;
  host.innerHTML = rows.map(r => {
    const num = r.removed ? '—' : String(++n).padStart(2, '0');
    const kind = r.kind === 'client' ? 'AI-kundeslide' : 'Masterdeck';
    const action = r.fixed
      ? `<span class="deck-slide-fixed">Altid med</span>`
      : `<button type="button" class="deck-slide-btn${r.removed ? ' is-undo' : ''}"
                 data-kind="${r.kind}" data-id="${escapeHtml(r.id)}">${r.removed ? 'Tag med igen' : 'Fjern'}</button>`;
    return `
      <div class="deck-slide${r.removed ? ' is-removed' : ''}${r.fixed ? ' deck-slide--fixed' : ''}">
        <span class="deck-slide-num">${num}</span>
        <span class="deck-slide-title">${escapeHtml(r.title)}</span>
        <span class="deck-slide-kind">${kind}</span>
        ${action}
      </div>`;
  }).join('');

  const count = $('#deck-list-count');
  if (count) count.textContent = String(n);

  host.querySelectorAll('.deck-slide-btn').forEach(btn => {
    btn.addEventListener('click', () => toggleDeckSlide(btn.dataset.kind, btn.dataset.id));
  });
}

// Master-slides fjernes af backend'en ud fra id. AI-kundeslidesne har ikke et
// id i deck-generatoren — de tegnes kun hvis der ER indhold til dem. Så en
// fjernet kundeslide sendes med tomt indhold. state.analysis røres ikke, så
// sælger kan fortryde uden at have mistet AI'ens tekst.
const CLIENT_SLIDE_CONTENT_KEYS = {
  research: 'research_facts',
  priorities: 'strategic_priorities',
  mapping: 'value_mappings',
  'next-steps': 'next_steps',
};

function analysisForDeck() {
  const a = state.analysis;
  if (!a || !clientSlideExclusions.size) return a;

  const copy = { ...a };
  clientSlideExclusions.forEach(id => {
    const key = CLIENT_SLIDE_CONTENT_KEYS[id];
    if (key) copy[key] = [];
    if (id === 'case') copy.case_recommendation = { ...(a.case_recommendation || {}), headline: '' };
  });
  return copy;
}

// Kontakt-sliden tegnes kun når et teammedlem er udfyldt
function teamForDeck() {
  const team = (state.brief && state.brief.team) || {};
  return clientSlideExclusions.has('contact') ? { kam: {}, rm: {} } : team;
}

function toggleDeckSlide(kind, id) {
  if (kind === 'client') {
    if (clientSlideExclusions.has(id)) clientSlideExclusions.delete(id);
    else clientSlideExclusions.add(id);
    // Vælgeren i brief-fanen tæller de samme slides — gen-tegn den også
    if (_planForPreview) renderSlidePlan(_planForPreview);
    else renderDeckSlideList();
    return;
  }

  const plan = _planForPreview;
  const slide = plan && (plan.library_slides || []).find(s => s.id === id);
  if (!slide) return;

  const isOn = (slide.id in slideOverrides) ? slideOverrides[slide.id] : slide.default_on;
  const next = !isOn;
  if (next === slide.default_on) delete slideOverrides[slide.id];
  else slideOverrides[slide.id] = next;

  if (next) deckRemovedMasterIds.delete(id);
  else deckRemovedMasterIds.add(id);

  // Gen-tegner både brief-fanens vælger og denne liste
  renderSlidePlan(plan);
}

// ---------- Build review UI ----------
// Overskrifterne er AI-genererede og står øverst på hvert kundeslide. De var
// ikke redigerbare, så sælgeren kunne rette brødteksten men ikke det største
// på sliden. **Stjerner** omkring et ord farver det som accent — samme
// markering som i decket.
function headlineFields(key) {
  const h = (state.analysis.slide_headlines || {})[key] || {};
  return `
    <div class="review-item review-item--headline">
      <span class="field-hint">Overskrift på sliden <em>— **stjerner** fremhæver et ord</em></span>
      <input class="editable" data-path="slide_headlines.${key}.eyebrow"
             value="${escapeHtml(h.eyebrow || '')}" placeholder="Lille tekst over overskriften">
      <input class="editable" data-path="slide_headlines.${key}.heading"
             value="${escapeHtml(h.heading || '')}" placeholder="Overskrift">
    </div>`;
}

function buildReviewUI() {
  const a = state.analysis;
  const c = $('#review-container');

  // Path-setteren skriver direkte i objektet — findes grenen ikke, fejler den
  a.slide_headlines = a.slide_headlines || {};
  ['research', 'priorities', 'mapping', 'next_steps'].forEach(k => {
    a.slide_headlines[k] = a.slide_headlines[k] || { eyebrow: '', heading: '' };
  });

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
    ${coverageMarkup(a.coverage_report)}

    ${deckListMarkup()}

    ${(a.research_facts || []).length ? `
    <div class="review-block">
      <div class="review-block-head">
        <h3>Research-fakta om ${escapeHtml(state.brief.client_name)}</h3>
      </div>
      ${headlineFields('research')}
      <div class="facts-list" id="facts-list"></div>
    </div>` : `
    <div class="review-block review-block--omitted">
      <div class="review-block-head"><h3>Intet research-slide</h3></div>
      <p class="review-omitted-note">
        AI'en fandt ikke research der understøtter din vinkel, så slidet er
        udeladt. Grunden står i «Sådan brugte jeg din brief» ovenfor.
        Vil du have det med alligevel, så skriv de fakta du selv vil vise
        under Avanceret i briefen og kør research igen.
      </p>
    </div>`}

    <div class="review-block">
      <div class="review-block-head">
        <h3>Strategiske prioriteter</h3>
        <span class="slide-ref" hidden>Slide 05</span>
      </div>
      
      ${headlineFields('priorities')}${priorities}
    </div>

    <div class="review-block">
      <div class="review-block-head">
        <h3>Udfordring → løsning mapping</h3>
        <span class="slide-ref" hidden>Slide 06</span>
      </div>
      
      ${headlineFields('mapping')}${mappings}
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
        <span class="slide-ref" hidden>Slide 17</span>
      </div>
      
      ${headlineFields('next_steps')}${steps}
    </div>
  `;

  // Bind edits på alt undtagen fakta (#facts-list er stadig tom her)
  bindEditables(c);

  // Fakta renderes for sig, så de kan gen-tegnes når sælger bytter en ud
  renderFacts();

  // Slide-listen gen-tegnes hver gang sælger fjerner eller fortryder
  renderDeckSlideList();

  // Foldbar dækningsrapport
  const covToggle = $('#coverage-toggle');
  const covBody = $('#coverage-body');
  if (covToggle && covBody) {
    covToggle.addEventListener('click', () => {
      const isOpen = !covBody.hidden;
      covBody.hidden = isOpen;
      covToggle.textContent = isOpen ? 'Vis rapport ↓' : 'Skjul ↑';
      covToggle.classList.toggle('is-expanded', !isOpen);
    });
  }
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
        analysis: analysisForDeck(),
        meeting: {
          date: state.brief.date,
          city: state.brief.city,
          contact_person: state.brief.contact_person,
        },
        team: teamForDeck(),
        pitch_length: state.brief.pitch_length,
        services: state.brief.services_to_highlight,
        stakeholder: state.brief.meeting_stakeholder,
        // Læses på ny her: sælger kan have fjernet slides i review-listen
        // efter research kørte
        excluded_slide_ids: currentExcludedSlideIds(),
        selected_slide_ids: currentSelectedSlideIds(),
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
        analysis: analysisForDeck(),
        meeting: {
          date: state.brief.date,
          city: state.brief.city,
          contact_person: state.brief.contact_person,
        },
        team: teamForDeck(),
        pitch_length: state.brief.pitch_length,
        services: state.brief.services_to_highlight,
        stakeholder: state.brief.meeting_stakeholder,
        excluded_slide_ids: currentExcludedSlideIds(),
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


// ---------- Live slide-plan ----------
let _planTimer = null;

function currentPlanParams() {
  const form = $('#brief-form');
  if (!form) return null;
  const length = form.querySelector('input[name="pitch_length"]:checked')?.value || 'medium';
  const stakeholder = form.querySelector('input[name="meeting_stakeholder"]:checked')?.value || '';
  const services = Array.from(form.querySelectorAll('input[name="services"]:checked')).map(c => c.value);
  return { length, stakeholder, services };
}

async function refreshSlidePlan() {
  const container = $('#slide-plan');
  if (!container) return;
  const params = currentPlanParams();
  if (!params) return;

  const qs = new URLSearchParams({ pitch_length: params.length });
  if (params.services.length) qs.set('services', params.services.join(','));
  if (params.stakeholder) qs.set('stakeholder', params.stakeholder);

  try {
    const res = await fetch(`${API_BASE}/api/slide-plan?${qs}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const plan = await res.json();
    renderSlidePlan(plan);
  } catch (e) {
    container.innerHTML = `<div class="slide-plan-loading">Kunne ikke hente slide-plan (${e.message})</div>`;
  }
}

// Sælgerens manuelle til-/fravalg — overlever at forvalget genberegnes
// når længde eller services ændres. id → true (til) / false (fra).
const slideOverrides = {};

// AI'ens begrundelse for sit slide-forslag. Bliver stående i vælgeren, så det
// er tydeligt hvem der satte fluebenene — også efter sælger selv har rettet.
let aiSlideAdvice = '';

// De master-slides der er slået til lige nu (sendes til generate-deck).
//
// Udregnes fra slideOverrides og planen — ikke fra afkrydsningsfelterne i DOM'en.
// Review-fanens "fjern slide" skriver til slideOverrides, men tegner ikke
// brief-fanens vælger om; læste vi DOM'en, ville et fravalg i review derfor
// aldrig nå med i det genererede deck.
function currentSelectedSlideIds() {
  const plan = _planForPreview;
  if (plan && Array.isArray(plan.library_slides)) {
    return plan.library_slides
      .filter(sl => (sl.id in slideOverrides) ? slideOverrides[sl.id] : sl.default_on)
      .map(sl => sl.id);
  }
  // Planen er ikke hentet endnu — fald tilbage til det vælgeren viser
  const container = $('#slide-plan');
  if (!container) return null;
  const boxes = container.querySelectorAll('.plan-slide input[type="checkbox"]');
  if (!boxes.length) return null;
  return Array.from(boxes).filter(c => c.checked).map(c => c.value);
}

// Alt sælger har fravalgt: master-slides fra vælgeren + AI-kundeslides han har
// fjernet i review-listen. Begge dele rejser i excluded_slide_ids.
function currentExcludedSlideIds() {
  const container = $('#slide-plan');
  const master = container
    ? Array.from(container.querySelectorAll('.plan-slide input[type="checkbox"]:not(:checked)')).map(c => c.value)
    : [];
  return master.concat(Array.from(clientSlideExclusions));
}

// AI'ens forslag sætter fluebenene. Vi skriver kun en override når valget
// afviger fra forvalget — ellers ville et senere skift af mødelængde blive
// spærret af overrides der bare gentog default_on.
async function applyRecommendedSlides(ids, reason) {
  if (!Array.isArray(ids) || !ids.length) return;
  if (!_planForPreview) await refreshSlidePlan();

  const plan = _planForPreview;
  if (!plan || !Array.isArray(plan.library_slides)) return;

  const wanted = new Set(ids.map(String));
  const known = plan.library_slides.filter(s => wanted.has(s.id));
  if (!known.length) return;   // ukendte id'er — rør ikke sælgers valg

  plan.library_slides.forEach(s => {
    const on = wanted.has(s.id);
    if (on === s.default_on) delete slideOverrides[s.id];
    else slideOverrides[s.id] = on;
  });

  aiSlideAdvice = (reason || '').trim()
    || `AI'en foreslår ${known.length} slides fra masterdecket ud fra dine svar.`;
  renderSlidePlan(plan);
}

// Vælgeren har to halvdele: en liste (hurtig at skimme, viser hvorfor noget
// mangler) og en miniature-visning (viser hvad sliden faktisk indeholder).
// Sælgeren kan ikke vælge fornuftigt ud fra en titel som "Fra A til Z", men
// 34 miniaturer er også for meget at læse — derfor begge, med listen som
// udgangspunkt og billederne et klik væk.
let _previewReady = false;

function currentSelection(plan) {
  const isOn = s => (s.id in slideOverrides) ? slideOverrides[s.id] : s.default_on;
  return plan.library_slides.filter(isOn).map(s => s.id);
}

function pushSelectionToPreview(plan) {
  const f = document.getElementById('slide-preview-frame');
  if (!f || !f.contentWindow || !_previewReady) return;
  f.contentWindow.postMessage(
    { type: 'slide-selection', ids: currentSelection(plan) }, '*');
}

function renderSlidePlan(plan) {
  const container = $('#slide-plan');
  const chapterLabels = plan.chapter_labels || {};
  const isOn = s => (s.id in slideOverrides) ? slideOverrides[s.id] : s.default_on;
  const shortName = x => x.replace('Epico ', '');

  // Gen-tegningen nulstiller <details>. Uden det her ville panelerne klappe i
  // hver gang sælgeren tilvalgte et slide.
  const wasOpen = !!container.querySelector('.plan-more[open]');
  const previewOpen = !!container.querySelector('.plan-preview[open]');

  // Sælgeren skal se sit deck først. Viste vi alle 34 med de fravalgte
  // overstreget, gav det ved et medium Freelance-møde 21 gennemstregede linjer
  // mod 13 aktive — det læses som "noget er i stykker".
  const on = plan.library_slides.filter(isOn);
  const off = plan.library_slides.filter(s => !isOn(s));

  // Kundeslides sælger har fjernet i review-listen tælles ikke med — men de
  // bliver stående som overstreget chip, så tallet ikke bare falder uforklaret.
  const fixedSlides = [...plan.client_slides, ...plan.closing_slides];
  const fixed = fixedSlides.map(s => {
    const off = clientSlideExclusions.has(clientSlideId(s));
    return `<span class="plan-chip${off ? ' plan-chip--off' : ''}">${escapeHtml(s.title)}</span>`;
  }).join('');

  const row = (s, checked) => `
    <label class="plan-slide">
      <input type="checkbox" value="${escapeHtml(s.id)}" ${checked ? 'checked' : ''}>
      <span class="plan-slide-title">${escapeHtml(s.title)}</span>
    </label>`;

  const onGroups = {};
  on.forEach(s => (onGroups[s.category] = onGroups[s.category] || []).push(s));
  const onHtml = Object.entries(onGroups).map(([cat, slides]) => `
    <div class="plan-group">
      <div class="plan-group-head">${escapeHtml(chapterLabels[cat] || cat)}</div>
      ${slides.map(s => row(s, true)).join('')}
    </div>`).join('');

  // Resten grupperes efter HVORFOR de mangler — grunden som overskrift i
  // stedet for et mærkat sælgeren selv skal tolke.
  const buckets = new Map();
  off.forEach(s => {
    const key = s.off_reason === 'service' && (s.unlock_services || []).length
      ? `Kræver at du vælger ${s.unlock_services.map(shortName).join(' eller ')}`
      : 'Ikke forvalgt ved denne mødelængde';
    (buckets.get(key) || buckets.set(key, []).get(key)).push(s);
  });
  const offHtml = [...buckets.entries()].map(([why, slides]) => `
    <div class="plan-group">
      <div class="plan-group-head plan-group-head--why">${escapeHtml(why)}</div>
      ${slides.map(s => row(s, false)).join('')}
    </div>`).join('');

  const fixedCount = fixedSlides.filter(s => !clientSlideExclusions.has(clientSlideId(s))).length;
  const updateSummary = () => {
    const n = container.querySelectorAll('.plan-slide input:checked').length;
    $('#plan-count').textContent = fixedCount + n;
    const bd = container.querySelector('.plan-breakdown');
    if (bd) bd.textContent = `${fixedCount} kunde-slides · ${n} fra masterdecket`;
  };

  container.innerHTML = `
    ${aiSlideAdvice ? `
      <div class="plan-ai-note">
        <span class="plan-ai-note-label">AI'ens forslag</span>
        <span class="plan-ai-note-text">${escapeHtml(aiSlideAdvice)}</span>
        <span class="plan-ai-note-hint">Fluebenene er sat af AI'en — ret dem frit.</span>
      </div>` : ''}

    <div class="plan-summary">
      <span class="plan-count" id="plan-count"></span>
      <span class="plan-count-label">slides i alt</span>
      <span class="plan-breakdown"></span>
    </div>

    <div class="plan-fixed">
      <div class="plan-group-head">Altid med</div>
      <div class="plan-chips">${fixed}</div>
    </div>

    ${onHtml || '<div class="slide-plan-loading">Masterdecket er ikke indlæst.</div>'}

    ${off.length ? `
      <details class="plan-more" ${wasOpen ? "open" : ""}>
        <summary class="plan-more-toggle">
          <span>${off.length} flere slides fra masterdecket</span>
          <span class="plan-more-hint">tilføj</span>
        </summary>
        <div class="plan-more-body">${offHtml}</div>
      </details>` : ''}

    <details class="plan-preview" ${previewOpen ? "open" : ""}>
      <summary class="plan-more-toggle">
        <span>Se hvad de enkelte slides indeholder</span>
        <span class="plan-more-hint">vis</span>
      </summary>
      <div class="plan-preview-body">
        <p class="plan-preview-note">
          Masterdecket som det ser ud uden kundetilpasning. Klik en miniature for
          at tage sliden med eller fra — de fremhævede er dem du får.
        </p>
        <iframe id="slide-preview-frame" title="Masterdeckets slides" loading="lazy"></iframe>
      </div>
    </details>
  `;

  container.querySelectorAll('.plan-slide input[type="checkbox"]').forEach(cb => {
    cb.addEventListener('change', () => {
      const def = plan.library_slides.find(s => s.id === cb.value)?.default_on;
      if (cb.checked === def) delete slideOverrides[cb.value];
      else slideOverrides[cb.value] = cb.checked;
      renderSlidePlan(plan);
    });
  });

  // Iframen indlæses først når sælgeren folder den ud — 850 KB skal ikke
  // hentes for de fleste, der bare kører videre med standardvalget.
  const details = container.querySelector('.plan-preview');
  const frame = container.querySelector('#slide-preview-frame');
  if (details && frame) {
    const load = () => {
      if (!frame.src) { _previewReady = false; frame.src = `${API_BASE}/api/master-preview`; }
      else pushSelectionToPreview(plan);
    };
    if (details.open) load();
    details.addEventListener('toggle', () => { if (details.open) load(); });
    frame.addEventListener('load', () => { _previewReady = true; pushSelectionToPreview(plan); });
  }

  _planForPreview = plan;
  updateSummary();
  pushSelectionToPreview(plan);

  // Review-listen viser de samme master-slides — hold de to i trit
  if ($('#deck-list')) renderDeckSlideList();
}

// Miniaturerne melder klik tilbage hertil; composeren ejer state, så de to
// visninger kan ikke komme ud af trit.
let _planForPreview = null;
addEventListener('message', e => {
  const d = e.data || {};
  const plan = _planForPreview;
  if (!plan) return;

  if (d.type === 'slide-toggle') {
    const slide = plan.library_slides.find(s => s.id === d.id);
    if (!slide) return;
    const isOn = (slide.id in slideOverrides) ? slideOverrides[slide.id] : slide.default_on;
    if (!isOn === slide.default_on) delete slideOverrides[slide.id];
    else slideOverrides[slide.id] = !isOn;
    renderSlidePlan(plan);
  }

  if (d.type === 'slide-preview-height') {
    const f = document.getElementById('slide-preview-frame');
    if (f && d.height) f.style.height = Math.min(d.height + 20, 2400) + 'px';
  }
});

function schedulePlanRefresh() {
  clearTimeout(_planTimer);
  _planTimer = setTimeout(refreshSlidePlan, 150);
}

// ---------- Init ----------
document.addEventListener('DOMContentLoaded', () => {
  checkHealth();
  setupUpload();
  refreshSlidePlan();

  // Opdater slide-planen når længde, services eller stakeholder ændres
  $$('input[name="pitch_length"], input[name="services"], input[name="meeting_stakeholder"]')
    .forEach(el => el.addEventListener('change', schedulePlanRefresh));

  $('#brief-form').addEventListener('submit', runResearch);
  $('#cvr-lookup-btn').addEventListener('click', lookupCVR);

  // Omvendt brief — knapperne er døde indtil der står et kundenavn
  const askBtn = $('#brief-questions-btn');
  const askMoreBtn = $('#brief-questions-more-btn');
  const clientNameInput = $('#brief-form [name="client_name"]');
  if (askBtn) askBtn.addEventListener('click', () => askBriefQuestions(false));
  if (askMoreBtn) askMoreBtn.addEventListener('click', () => askBriefQuestions(true));
  if (clientNameInput) clientNameInput.addEventListener('input', updateBriefQuestionsBtn);

  // Vejen udenom: nogle sælgere kender kunden bedre end AI'en når til på tre
  // runder, og en hård blokering ville gøre værktøjet til en tidsrøver.
  const skipBtn = $('#brief-questions-skip-btn');
  if (skipBtn) skipBtn.addEventListener('click', () => {
    unlockResearch('skipped');
    updateBriefQuestionsUi();
    const actions = $('#run-analysis-btn');
    if (actions) actions.scrollIntoView({ behavior: 'smooth', block: 'center' });
  });

  updateBriefQuestionsUi();

  // Retter sælger selv i et brief-felt, må vores AI-svar ikke overskrive det
  Object.keys(BRIEF_FIELD_LABELS).forEach(field => {
    const el = briefFieldEl(field);
    if (el) el.addEventListener('input', () => handleManualBriefEdit(field));
  });

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


  // Collapse toggle for Avanceret
  const advToggle = $('#advanced-toggle');
  const advFields = $('#advanced-fields');
  if (advToggle && advFields) {
    advToggle.addEventListener('click', () => {
      const isOpen = !advFields.hidden;
      advFields.hidden = isOpen;
      advToggle.textContent = isOpen ? 'Vis felter ↓' : 'Skjul felter ↑';
      advToggle.classList.toggle('is-expanded', !isOpen);
    });
  }

  // Collapse toggle for slide-dictation (inde i Avanceret)
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

  // Sælgerens eget team er det samme hver gang — hent det fra sidste deck
  setupTeam();

  // Sæt dato til i dag som default
  const dateInput = $('input[name="date"]');
  if (dateInput) dateInput.value = new Date().toISOString().split('T')[0];

  // Sæt by til København som default
  const cityInput = $('input[name="city"]');
  if (cityInput && !cityInput.value) cityInput.value = 'København';
});
