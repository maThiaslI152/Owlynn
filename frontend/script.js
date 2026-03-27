// ─── Backend URL Detection ─────────────────────────────────────────────────
// When running inside Tauri, location.host points to tauri://localhost (not the backend).
// Detect this and fall back to the known backend address.
const _isTauri = Boolean(window.__TAURI__ || location.protocol === 'tauri:' || !location.host || location.host === 'localhost');
const API_BASE = _isTauri ? 'http://127.0.0.1:8000' : '';
const WS_BASE = _isTauri ? 'ws://127.0.0.1:8000' : `ws://${location.host}`;

// State management
let currentSessionId = generateUUID();
let socket = null;
let isReasoning = false;
let pendingFiles = []; // { name, type, data (base64), preview? }
let currentSubPath = ''; // Tracks current folder level in workspace view
let hasSentMessageInCurrentSession = false; // Draft tracking for "New chat" UX
let chatRegisteredInBackend = false; // Whether this thread is registered in the project recents list
let chatProjectIdForThread = 'default'; // Project context used for agent calls + chat registration
let titleGenerationInFlight = false; // Prevent duplicate title generations
let websocketThreadId = null; // Track which thread the websocket is bound to
let activeMode = 'tools_on'; // 'tools_on' = local tools + optional web (see webSearchEnabled)
/** When false, backend omits web_search from the tool list (other tools stay on). */
let webSearchEnabled = true;
/** normal | learning | concise | explanatory | formal — sent to LLM system hints */
let responseStyle = 'normal';
let activeProjectId = null;
let hasSelectedProject = false;
let currentChatName = '';
let activeAiMessage = null; 
let lastHumanMessage = ""; // For regenerate
let currentModelUsed = "unknown"; // Track which model is being used
let thinkingIndicatorEl = null;
let activeToolName = null;
const liveToolCards = new Map();
let currentView = 'welcome';
let cachedProjects = [];
let cachedArtifacts = [];
let cachedTools = [];
let cachedChats = [];
let activeArtifactTab = 'inspiration';
let activeArtifactFilter = 'all';
let customizeTab = 'skills';
let spotlightResultsFlat = [];
let spotlightSelectedIndex = 0;

// Helper function to render tool execution cards
function renderToolExecution(toolName, status = 'running', input = null, output = null, error = null) {
    const card = document.createElement('div');
    card.className = 'tool-execution-card';
    
    let statusBadge = '';
    if (status === 'running') {
        statusBadge = '<span class="tool-status-badge tool-status-running"><span class="w-2 h-2 rounded-full bg-yellow-600 animate-pulse"></span>Running...</span>';
    } else if (status === 'success') {
        statusBadge = '<span class="tool-status-badge tool-status-success"><span class="w-2 h-2 rounded-full bg-green-600"></span>Completed</span>';
    } else if (status === 'error') {
        statusBadge = '<span class="tool-status-badge tool-status-error"><span class="w-2 h-2 rounded-full bg-red-600"></span>Failed</span>';
    }
    
    let inputHtml = '';
    if (input) {
        inputHtml = `<div class="tool-input"><strong>Input:</strong><div class="mt-1 text-gray-700">${DOMPurify.sanitize(input)}</div></div>`;
    }
    
    let outputHtml = '';
    if (output) {
        const raw = String(output);
        const longOut = raw.length > 600;
        const safe = DOMPurify.sanitize(raw);
        if (longOut) {
            outputHtml = `<details class="tool-output-details mt-2 border-t border-bordercolor pt-2"><summary class="cursor-pointer text-xs font-semibold text-gray-600 hover:text-gray-900">Raw tool output (${raw.length} chars) — click to expand</summary><div class="tool-output mt-2 max-h-[min(50vh,420px)] overflow-y-auto text-gray-700 text-sm whitespace-pre-wrap break-words">${safe}</div></details>`;
        } else {
            outputHtml = `<div class="tool-output"><strong>Output:</strong><div class="mt-1 text-gray-700">${safe}</div></div>`;
        }
    }
    
    let errorHtml = '';
    if (error) {
        errorHtml = `<div class="tool-input tool-error"><strong>Error:</strong><div class="mt-1 text-red-700">${DOMPurify.sanitize(error)}</div></div>`;
    }
    
    card.innerHTML = `
        <div class="tool-header">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 1 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>
            <span>${DOMPurify.sanitize(String(toolName || 'tool'))}</span>
            ${statusBadge}
        </div>
        ${inputHtml}
        ${outputHtml}
        ${errorHtml}
    `;
    
    return card;
}

// Helper function to render error messages
function renderErrorMessage(title, message, details = null) {
    const div = document.createElement('div');
    div.className = 'error-message';
    
    let html = `<strong>⚠️ ${DOMPurify.sanitize(title)}</strong><p>${DOMPurify.sanitize(message)}</p>`;
    if (details) {
        html += `<div class="text-sm mt-2 opacity-90"><code>${DOMPurify.sanitize(details)}</code></div>`;
    }
    
    div.innerHTML = html;
    return div;
}

// Helper function for loading skeleton
function renderLoadingSkeleton() {
    const div = document.createElement('div');
    div.className = 'space-y-2';
    div.innerHTML = `
        <div class="skeleton-loader" style="width: 85%;"></div>
        <div class="skeleton-loader" style="width: 95%;"></div>
        <div class="skeleton-loader" style="width: 70%;"></div>
    `;
    return div;
}

function formatToolLabel(name) {
    if (!name) return "";
    return String(name).replace(/_/g, ' ');
}

function showThinkingIndicator() {
    if (thinkingIndicatorEl) return;
    const wrapper = document.createElement('div');
    wrapper.className = 'flex gap-4 group-msg mb-6';
    wrapper.dataset.sender = 'agent-thinking';

    const avatar = document.createElement('div');
    avatar.className = 'w-8 h-8 rounded shrink-0 bg-anthropic flex items-center justify-center text-white mt-1';
    avatar.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 8V4H8"/><rect x="4" y="8" width="16" height="12" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/></svg>';
    wrapper.appendChild(avatar);

    const content = document.createElement('div');
    content.className = 'flex-1 message-content text-base text-textdark';
    content.innerHTML = `
        <div class="thinking-pill">
            <span class="thinking-dot"></span>
            <span id="thinkingText">Owlynn is thinking...</span>
        </div>
    `;
    wrapper.appendChild(content);
    messagesArea.appendChild(wrapper);
    thinkingIndicatorEl = wrapper;
    scrollToBottom(true);
}

function updateThinkingIndicatorText() {
    if (!thinkingIndicatorEl) return;
    const textEl = thinkingIndicatorEl.querySelector('#thinkingText');
    if (!textEl) return;
    textEl.textContent = activeToolName
        ? `Running tool: ${formatToolLabel(activeToolName)}`
        : 'Owlynn is thinking...';
}

function clearThinkingIndicator() {
    if (!thinkingIndicatorEl) return;
    thinkingIndicatorEl.remove();
    thinkingIndicatorEl = null;
}

function resetTransientExecutionUI() {
    clearThinkingIndicator();
    activeToolName = null;
    liveToolCards.clear();
}

/**
 * DOM anchor for streamed answer + live tool cards: keep tools above the answer and
 * the answer above footer actions (copy/regenerate), not at the very end of the bubble.
 */
function getAgentAnswerAnchor(contentDiv) {
    if (!contentDiv) return null;
    return contentDiv.querySelector('.agent-final-answer')
        || contentDiv.querySelector('.message-actions');
}

/** Insert a live tool card above the streamed/final answer (and above message actions). */
function insertAgentToolCard(contentDiv, toolCard) {
    if (!contentDiv || !toolCard) return;
    const anchor = getAgentAnswerAnchor(contentDiv);
    if (anchor) {
        contentDiv.insertBefore(toolCard, anchor);
    } else {
        contentDiv.appendChild(toolCard);
    }
}

/** Keep streamed final answer after tool cards but before .message-actions. */
function moveActiveAnswerToEnd() {
    if (!activeAiMessage?.mainContainer || !activeAiMessage?.contentDiv) return;
    activeAiMessage.mainContainer.classList.add('agent-final-answer');
    const cd = activeAiMessage.contentDiv;
    const actions = cd.querySelector('.message-actions');
    if (actions) {
        cd.insertBefore(activeAiMessage.mainContainer, actions);
    } else {
        cd.appendChild(activeAiMessage.mainContainer);
    }
}

// DOM Elements
const chatContainer = document.getElementById('chatContainer');
const messagesArea = document.getElementById('messagesArea');
const chatForm = document.getElementById('chatForm');
const messageInput = document.getElementById('messageInput');
const sendBtn = document.getElementById('sendBtn');
const welcomePane = document.getElementById('view-welcome');
const sessionIdEl = document.getElementById('sessionId');
const newChatBtn = document.getElementById('newChatBtn');
const statusDot = document.getElementById('connectionStatusDot');
const statusText = document.getElementById('connectionStatusText');
const mobileDot = document.getElementById('mobileConnectionDot');
const agentStatus = document.getElementById('agentStatus');
const dragOverlay = document.getElementById('dragOverlay');
const attachmentPreviews = document.getElementById('attachmentPreviews');
const welcomeAttachmentPreviews = document.getElementById('welcomeAttachmentPreviews');
const fileInput = document.getElementById('fileInput');
const attachBtn = document.getElementById('attachBtn'); // legacy; may be null (composer + menu)
const modeFastBtn = document.getElementById('modeFastBtn');
const modeReasoningBtn = document.getElementById('modeReasoningBtn');
const projectsListEl = document.getElementById('projectsList');
const addProjectBtn = document.getElementById('addProjectBtn');
const projectKnowledgeSection = document.getElementById('projectKnowledgeSection');
const projectFilesList = document.getElementById('projectFilesList');
const projectChatsSection = document.getElementById('sidebarRecentsList'); // Wrapper/Section
const projectChatsList = document.getElementById('sidebarRecentsList');    // List container

// Settings Modal DOM Elements
const settingsModal = document.getElementById('settingsModal');
const openSettingsBtn = document.getElementById('openSettingsBtn');
const closeSettingsBtn = document.getElementById('closeSettingsBtn');
const closeSettingsFooterBtn = document.getElementById('closeSettingsFooterBtn');

// Sidebar DOM Elements
const profileNameInput = document.getElementById('profileName');
const profileLangInput = document.getElementById('profileLang');
const profileStyleInput = document.getElementById('profileStyle');
const profileLlmUrlInput = document.getElementById('profileLlmUrl');
const profileLlmModelInput = document.getElementById('profileLlmModel');
const saveProfileBtn = document.getElementById('saveProfileBtn');

const personaNameInput = document.getElementById('personaName');
const personaToneInput = document.getElementById('personaTone');
const savePersonaBtn = document.getElementById('savePersonaBtn');

const agentNameDisplay = document.getElementById('agentNameDisplay');
const agentRoleDisplay = document.getElementById('agentRoleDisplay');
const memoriesCountEl = document.getElementById('memoriesCount');

const newMemoryInput = document.getElementById('newMemoryInput');
const addMemoryBtn = document.getElementById('addMemoryBtn');
const memoriesListEl = document.getElementById('memoriesList');

// Initialize
    if (sessionIdEl) sessionIdEl.value = currentSessionId;
connectWebSocket();
initComposerUI();
loadSettingsData();
loadProjects();
setWorkspaceVisibility();

async function loadSettingsData() {
    try {
        const [profileRes, personaRes, memoriesRes, systemRes, advancedRes, topicsRes, interestsRes, conversationsRes] = await Promise.all([
            fetch(API_BASE + '/api/profile'),
            fetch(API_BASE + '/api/persona'),
            fetch(API_BASE + '/api/memories'),
            fetch(API_BASE + '/api/system-settings').catch(() => null),
            fetch(API_BASE + '/api/advanced-settings').catch(() => null),
            fetch(API_BASE + '/api/topics').catch(() => null),
            fetch(API_BASE + '/api/interests').catch(() => null),
            fetch(API_BASE + '/api/conversations').catch(() => null)
        ]);
        
        const profile = await profileRes.json();
        const persona = await personaRes.json();
        const memories = await memoriesRes.json();
        const systemSettings = systemRes ? await systemRes.json() : {};
        const advancedSettings = advancedRes ? await advancedRes.json() : {};
        const topicsData = topicsRes ? await topicsRes.json() : { topics: [] };
        const interestsData = interestsRes ? await interestsRes.json() : { interests: [] };
        const conversationsData = conversationsRes ? await conversationsRes.json() : { conversations: [] };

        // Populate Profile
        if (profileNameInput) profileNameInput.value = profile.name || '';
        // Update welcome heading and sidebar profile name
        const welcomeH = document.getElementById('welcomeHeading');
        if (welcomeH) welcomeH.textContent = `Welcome, ${profile.name || 'User'}`;
        const profileDisp = document.getElementById('profileNameDisplay');
        if (profileDisp) profileDisp.textContent = profile.name || 'User';
        const profileAvatar = document.querySelector('.profile-avatar');
        if (profileAvatar) profileAvatar.textContent = (profile.name || 'U')[0].toUpperCase();
        if (profileLangInput) profileLangInput.value = profile.preferred_language || 'en';
        if (profileStyleInput) profileStyleInput.value = profile.response_style || 'detailed';
        if (profileLlmUrlInput) profileLlmUrlInput.value = profile.llm_base_url || 'http://127.0.0.1:8080/v1';
        if (profileLlmModelInput) profileLlmModelInput.value = profile.llm_model_name || 'qwen/qwen3.5-9b';
        // Populate new small/large LLM fields
        const smallUrlEl = document.getElementById('profileSmallLlmUrl');
        const smallModelEl = document.getElementById('profileSmallLlmModel');
        const largeUrlEl = document.getElementById('profileLargeLlmUrl');
        const largeModelEl = document.getElementById('profileLargeLlmModel');
        if (smallUrlEl) smallUrlEl.value = profile.small_llm_base_url || 'http://127.0.0.1:1234/v1';
        if (smallModelEl) smallModelEl.value = profile.small_llm_model_name || '';
        if (largeUrlEl) largeUrlEl.value = profile.large_llm_base_url || 'http://127.0.0.1:1234/v1';
        if (largeModelEl) largeModelEl.value = profile.large_llm_model_name || '';

        updateComposerStyleQuickLabel();

        // Populate Persona
        if (personaNameInput) personaNameInput.value = persona.name || '';
        if (personaToneInput) personaToneInput.value = persona.tone || '';
        if (agentNameDisplay) agentNameDisplay.innerHTML = `
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-anthropic"><path d="M12 2a8 8 0 0 0-8 8c0 5.4 7.05 11.5 7.35 11.76a1 1 0 0 0 1.3 0C12.95 21.5 20 15.4 20 10a8 8 0 0 0-8-8z"/><circle cx="12" cy="10" r="3"/></svg>
            ${persona.name || 'Owlynn'}
        `;
        if (agentRoleDisplay) agentRoleDisplay.innerText = persona.role || '';

        // Populate System Settings
        if (systemPromptInput) {
            systemPromptInput.value = systemSettings.system_prompt || DEFAULT_SYSTEM_PROMPT;
        }
        if (customInstructionsInput) {
            customInstructionsInput.value = systemSettings.custom_instructions || '';
        }

        // Populate Advanced Settings
        if (temperatureSlider) {
            temperatureSlider.value = advancedSettings.temperature || 0.7;
            if (temperatureValue) temperatureValue.textContent = parseFloat(temperatureSlider.value).toFixed(1);
        }
        if (topPSlider) {
            topPSlider.value = advancedSettings.top_p || 0.9;
            if (topPValue) topPValue.textContent = parseFloat(topPSlider.value).toFixed(2);
        }
        if (maxTokensSlider) {
            maxTokensSlider.value = advancedSettings.max_tokens || 2048;
            if (maxTokensValue) maxTokensValue.textContent = parseInt(maxTokensSlider.value);
        }
        if (topKSlider) {
            topKSlider.value = advancedSettings.top_k || 40;
            if (topKValue) topKValue.textContent = parseInt(topKSlider.value);
        }
        if (streamingToggle) streamingToggle.checked = advancedSettings.streaming_enabled !== false;
        if (thinkingToggle) thinkingToggle.checked = advancedSettings.show_thinking || false;
        if (toolVisibilityToggle) toolVisibilityToggle.checked = advancedSettings.show_tool_execution !== false;

        // Populate Memories
        if (memoriesCountEl) memoriesCountEl.innerText = memories.length || 0;
        renderMemories(memories);

        // Populate Topics
        renderTrackedTopics(topicsData.topics || []);

        // Populate Interests
        renderDetectedInterests(interestsData.interests || []);

        // Populate Conversations
        renderRecentConversations(conversationsData.conversations || []);

    } catch (e) {
        console.error('Failed to load settings data:', e);
    }
}

function updateComposerStyleQuickLabel() {
    const el = document.getElementById('composerStyleQuickLabel');
    const welcomeEl = document.getElementById('welcomeStyleLabel');
    const styleMap = {
        normal: 'Normal',
        learning: 'Learning',
        concise: 'Concise',
        explanatory: 'Explanatory',
        formal: 'Formal',
    };
    const text = `Style: ${styleMap[responseStyle] || 'Normal'}`;
    if (el) el.textContent = text;
    if (welcomeEl) welcomeEl.textContent = text;
}

function buildChatWsPayload(messageText, filesPayload) {
    return {
        message: messageText,
        files: filesPayload,
        mode: activeMode,
        web_search_enabled: webSearchEnabled,
        response_style: responseStyle,
        project_id: getChatProjectId(),
    };
}

function setComposerWebSearchUI() {
    const chk = document.getElementById('composerWebSearchCheck');
    if (chk) chk.classList.toggle('hidden', !webSearchEnabled);
    const row = document.getElementById('composerMenuWebSearch');
    if (row) row.setAttribute('aria-pressed', webSearchEnabled ? 'true' : 'false');
}

function setComposerStyleUI() {
    document.querySelectorAll('.composer-style-option').forEach((b) => {
        const st = b.getAttribute('data-style');
        const check = b.querySelector('.style-check');
        const on = st === responseStyle;
        b.classList.toggle('active-style', on);
        if (check) check.classList.toggle('hidden', !on);
    });
    updateComposerStyleQuickLabel();
}

function closeComposerPlusMenu() {
    document.getElementById('composerPlusMenu')?.classList.add('hidden');
    document.getElementById('composerStyleSubmenu')?.classList.add('hidden');
    document.getElementById('composerPlusBtn')?.setAttribute('aria-expanded', 'false');
}

/** Clamp for viewport positioning */
function clampComposer(n, min, max) {
    return Math.max(min, Math.min(max, n));
}

/**
 * Position fixed menu above anchor. align: 'start' | 'end' (match left or right edge like style pill).
 */
function positionMenuAboveAnchor(menuEl, anchorEl, align = 'start', gap = 8) {
    if (!menuEl || !anchorEl) return;
    menuEl.style.position = 'fixed';
    menuEl.classList.remove('hidden');
    const ar = anchorEl.getBoundingClientRect();
    let br = menuEl.getBoundingClientRect();
    let top = ar.top - br.height - gap;
    let left = align === 'end' ? ar.right - br.width : ar.left;
    if (top < 8) {
        top = ar.bottom + gap;
    }
    top = clampComposer(top, 8, window.innerHeight - br.height - 8);
    left = clampComposer(left, 8, window.innerWidth - br.width - 8);
    menuEl.style.top = `${Math.round(top)}px`;
    menuEl.style.left = `${Math.round(left)}px`;
}

function positionStyleSubmenuBesideMainMenu() {
    const main = document.getElementById('composerPlusMenu');
    const sub = document.getElementById('composerStyleSubmenu');
    if (!main || !sub || main.classList.contains('hidden')) return;
    sub.style.position = 'fixed';
    sub.classList.remove('hidden');
    const mr = main.getBoundingClientRect();
    let sr = sub.getBoundingClientRect();
    let left = mr.right + 8;
    let top = mr.bottom - sr.height;
    if (left + sr.width > window.innerWidth - 8) {
        left = mr.left - sr.width - 8;
    }
    top = clampComposer(top, 8, window.innerHeight - sr.height - 8);
    left = clampComposer(left, 8, window.innerWidth - sr.width - 8);
    sub.style.top = `${Math.round(top)}px`;
    sub.style.left = `${Math.round(left)}px`;
}

function toggleComposerPlusMenu(anchorEl) {
    const menu = document.getElementById('composerPlusMenu');
    const sub = document.getElementById('composerStyleSubmenu');
    const plus = document.getElementById('composerPlusBtn');
    if (!menu || !anchorEl) return;
    if (!menu.classList.contains('hidden')) {
        closeComposerPlusMenu();
        return;
    }
    sub?.classList.add('hidden');
    positionMenuAboveAnchor(menu, anchorEl, 'start', 8);
    plus?.setAttribute('aria-expanded', 'true');
}

/** Style pill: only the style list (not the full + menu). */
function toggleStyleSubmenuOnly(anchorEl) {
    const menu = document.getElementById('composerPlusMenu');
    const sub = document.getElementById('composerStyleSubmenu');
    if (!sub || !anchorEl) return;
    if (!sub.classList.contains('hidden')) {
        sub.classList.add('hidden');
        return;
    }
    menu?.classList.add('hidden');
    document.getElementById('composerPlusBtn')?.setAttribute('aria-expanded', 'false');
    positionMenuAboveAnchor(sub, anchorEl, 'end', 8);
}

function initComposerUI() {
    const plus = document.getElementById('composerPlusBtn');
    const menu = document.getElementById('composerPlusMenu');
    if (!plus || !menu) return;

    plus.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleComposerPlusMenu(plus);
    });

    document.getElementById('composerMenuAttach')?.addEventListener('click', (e) => {
        e.stopPropagation();
        fileInput?.click();
        closeComposerPlusMenu();
    });

    document.getElementById('composerMenuWebSearch')?.addEventListener('click', (e) => {
        e.stopPropagation();
        webSearchEnabled = !webSearchEnabled;
        setComposerWebSearchUI();
    });

    document.getElementById('composerMenuStyleBtn')?.addEventListener('click', (e) => {
        e.stopPropagation();
        const sub = document.getElementById('composerStyleSubmenu');
        const main = document.getElementById('composerPlusMenu');
        if (!sub || !main || main.classList.contains('hidden')) return;
        if (sub.classList.contains('hidden')) {
            positionStyleSubmenuBesideMainMenu();
        } else {
            sub.classList.add('hidden');
        }
    });

    document.querySelectorAll('.composer-style-option').forEach((btn) => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            responseStyle = btn.getAttribute('data-style') || 'normal';
            setComposerStyleUI();
            closeComposerPlusMenu();
        });
    });

    document.getElementById('composerMenuProject')?.addEventListener('click', (e) => {
        e.stopPropagation();
        closeComposerPlusMenu();
        document.getElementById('nav-projects')?.click();
    });

    document.getElementById('composerMenuGithub')?.addEventListener('click', (e) => {
        e.stopPropagation();
        closeComposerPlusMenu();
        alert('GitHub import is coming soon.');
    });

    document.getElementById('composerMenuConnectors')?.addEventListener('click', (e) => {
        e.stopPropagation();
        closeComposerPlusMenu();
        document.getElementById('nav-customize')?.click();
        document.getElementById('customizeConnectorsTabBtn')?.click();
    });

    document.getElementById('composerStyleQuickBtn')?.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleStyleSubmenuOnly(e.currentTarget);
    });

    document.addEventListener('click', (ev) => {
        if (
            ev.target.closest?.('#composerPlusBtn') ||
            ev.target.closest?.('#composerPlusMenu') ||
            ev.target.closest?.('#welcomeAttachBtn') ||
            ev.target.closest?.('#welcomeStyleBtn') ||
            ev.target.closest?.('#composerStyleQuickBtn') ||
            ev.target.closest?.('#composerStyleSubmenu')
        ) {
            return;
        }
        closeComposerPlusMenu();
    });

    setComposerWebSearchUI();
    setComposerStyleUI();
    updateComposerStyleQuickLabel();
}

function renderMemories(memories) {
    if (!memoriesListEl) return;
    memoriesListEl.innerHTML = '';
    
    if (memories.length === 0) {
        memoriesListEl.innerHTML = '<p class="text-xs text-gray-400 italic text-center py-4">No memories stored yet.</p>';
        return;
    }
    
    memories.forEach(m => {
        const item = document.createElement('div');
        item.className = 'flex items-center justify-between gap-3 p-3 bg-cloud border border-bordercolor rounded-xl text-sm group hover:border-anthropic/30 transition-colors';
        
        item.innerHTML = `
            <div class="flex-1">
                <p class="text-textdark font-medium">${m.fact}</p>
                <p class="text-[10px] text-gray-400 mt-1">${new Date(m.timestamp).toLocaleString()}</p>
            </div>
            <button class="delete-memory-btn p-1.5 rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 transition-all opacity-0 group-hover:opacity-100" title="Delete Memory">
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>
            </button>
        `;
        
        item.querySelector('.delete-memory-btn').onclick = () => deleteMemory(m.fact);
        memoriesListEl.appendChild(item);
    });
}

async function deleteMemory(fact) {
    const confirmed = await showCustomConfirm('Forget Memory', `Are you sure you want to forget: "${fact}"?`, true);
    if (!confirmed) return;
    
    try {
        const res = await fetch(API_BASE + '/api/memories', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ fact })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            if (memoriesCountEl) memoriesCountEl.innerText = data.memories.length;
            renderMemories(data.memories);
        }
    } catch (e) {
        console.error('Failed to delete memory:', e);
    }
}

function renderTrackedTopics(topics) {
    const topicsEl = document.getElementById('trackedTopics');
    if (!topicsEl) return;
    
    topicsEl.innerHTML = '';
    if (topics.length === 0) {
        topicsEl.innerHTML = '<span class="text-[12px] text-gray-500 italic">No topics tracked yet. They will appear as you chat.</span>';
        return;
    }
    
    topics.forEach(topic => {
        const badge = document.createElement('div');
        badge.className = 'inline-flex items-center gap-2 px-3 py-1.5 bg-blue-100 text-blue-700 rounded-full text-[12px] font-medium border border-blue-200';
        badge.innerHTML = `
            <span>🏷️ ${topic.topic || topic}</span>
            ${topic.count ? `<span class="text-[10px] bg-blue-200 px-1.5 py-0.5 rounded-full">${topic.count}</span>` : ''}
        `;
        topicsEl.appendChild(badge);
    });
}

function renderDetectedInterests(interests) {
    const interestsEl = document.getElementById('detectedInterests');
    if (!interestsEl) return;
    
    interestsEl.innerHTML = '';
    if (interests.length === 0) {
        interestsEl.innerHTML = '<span class="text-[12px] text-gray-500 italic">No interests detected yet. I\'ll learn about you as we chat.</span>';
        return;
    }
    
    interests.forEach(interest => {
        const chip = document.createElement('div');
        chip.className = 'inline-flex items-center gap-2 px-3 py-1.5 bg-green-100 text-green-700 rounded-full text-[12px] font-medium border border-green-200';
        const interestLabel = interest.interest || interest;
        chip.innerHTML = `
            <span>✨ ${interestLabel}</span>
            ${interest.count ? `<span class="text-[10px] bg-green-200 px-1.5 py-0.5 rounded-full">${interest.count}</span>` : ''}
        `;
        interestsEl.appendChild(chip);
    });
}

function renderRecentConversations(conversations) {
    const conversationsEl = document.getElementById('recentConversations');
    if (!conversationsEl) return;
    
    conversationsEl.innerHTML = '';
    if (conversations.length === 0) {
        conversationsEl.innerHTML = '<span class="text-[12px] text-gray-500 italic">No conversations recorded yet.</span>';
        return;
    }
    
    conversations.slice(0, 5).forEach((conv, idx) => {
        const card = document.createElement('div');
        card.className = 'p-2.5 bg-white border border-purple-200 rounded-lg hover:border-purple-300 hover:bg-purple-50 transition-colors cursor-pointer';
        const summary = (conv.summary || conv.user_message || 'Conversation').substring(0, 60) + '...';
        const timestamp = conv.timestamp ? new Date(conv.timestamp).toLocaleDateString() : 'Recent';
        card.innerHTML = `
            <p class="text-[12px] font-medium text-gray-700">${summary}</p>
            <p class="text-[10px] text-gray-500 mt-1">${timestamp}</p>
        `;
        conversationsEl.appendChild(card);
    });
}

addMemoryBtn?.addEventListener('click', async () => {
    const fact = newMemoryInput.value.trim();
    if (!fact) return;
    
    try {
        const res = await fetch(API_BASE + '/api/memories', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ fact })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            newMemoryInput.value = '';
            if (memoriesCountEl) memoriesCountEl.innerText = data.memories.length;
            renderMemories(data.memories);
        }
    } catch (e) {
        console.error('Failed to add memory:', e);
    }
});

async function loadProjects() {
    try {
        const res = await fetch(API_BASE + '/api/projects');
        const projects = await res.json();
        cachedProjects = projects;
        renderProjects(projects);
        renderWelcomeRecents();
        renderProjectInspector(projects.find((p) => p.id === activeProjectId) || null);
        setWorkspaceVisibility();
        // Populate sidebar recents from the active/default project
        const activeProject = projects.find((p) => p.id === getEffectiveProjectId());
        if (activeProject) {
            renderProjectChats(activeProject.chats || []);
        }
    } catch (e) {
        console.error('Failed to load projects:', e);
    }
}

function renderProjects(projects) {
    if (!projectsListEl) return;
    projectsListEl.innerHTML = '';
    
    projects.forEach(project => {
        const isActive = project.id === activeProjectId;
        const item = document.createElement('div');
        item.className = `group flex items-center gap-2 px-2 py-1.5 rounded-md text-sm cursor-pointer transition-colors ${
            isActive ? 'bg-white border border-anthropic/20 shadow-sm' : 'hover:bg-gray-100 text-gray-600'
        }`;
        
        item.innerHTML = `
            <span class="w-2 h-2 rounded-full ${isActive ? 'bg-anthropic' : 'bg-gray-300'}"></span>
            <span class="truncate flex-1 ${isActive ? 'font-medium text-textdark' : ''}">${project.name}</span>
            ${project.id !== 'default' ? `
            <div class="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                <button class="edit-project-btn p-1 rounded-md hover:bg-gray-200 text-gray-400 hover:text-anthropic" title="Rename Project">
                    <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>
                </button>
                <button class="delete-project-btn p-1 rounded-md hover:bg-gray-200 text-gray-400 hover:text-red-500" title="Delete Project">
                    <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                </button>
            </div>
            ` : ''}
        `;
        
        item.querySelector('.edit-project-btn')?.addEventListener('click', (e) => {
            e.stopPropagation();
            editProject(project.id, project.name);
        });
        
        item.querySelector('.delete-project-btn')?.addEventListener('click', (e) => {
            e.stopPropagation();
            deleteProject(project.id, project.name);
        });
        
        item.onclick = () => switchProject(project.id);
        projectsListEl.appendChild(item);
    });
}

async function switchProject(projectId, resetChat = true) {
    activeProjectId = projectId;
    hasSelectedProject = true;
    localStorage.setItem('active_project_id', projectId);
    currentSubPath = ''; // Reset folder view on project swap
    setWorkspaceVisibility();
    loadWorkspaceFiles(); // Trigger workspace partition reload
    
    try {
        const res = await fetch(`${API_BASE}/api/projects/${projectId}`);
        const project = await res.json();
        currentChatName = '';
        renderProjectInspector(project);
        
        // Update UI
        if (projectKnowledgeSection) {
            projectKnowledgeSection.classList.toggle('hidden', !project.files || project.files.length === 0);
        }
        renderProjectFiles(project.files || []);
        
        // Render project chats
        if (projectChatsSection) {
            projectChatsSection.classList.toggle('hidden', !project.chats || project.chats.length === 0);
        }
        renderProjectChats(project.chats || []);
        
        // Reload projects list to update active state
        const allRes = await fetch(API_BASE + '/api/projects');
        const allProjects = await allRes.json();
        cachedProjects = allProjects;
        renderProjects(allProjects);
        renderWelcomeRecents();
        
        if (resetChat) {
            // Reset reasoning state
            updateAgentStatus('idle');
            
            // Load project-specific session ID
            const savedSessionId = localStorage.getItem(`project_session_${projectId}`);
            if (savedSessionId) {
                chatProjectIdForThread = projectId;
                currentSessionId = savedSessionId;
                if (sessionIdEl) sessionIdEl.value = currentSessionId;
                await loadChatHistory(currentSessionId);
                const selectedChat = (project.chats || []).find((c) => c.id === currentSessionId);
                currentChatName = selectedChat?.name || '';
                chatRegisteredInBackend = Boolean(selectedChat);
                
                // Reconnect WebSocket to the correct thread
                if (socket) {
                    socket.onclose = null; // Prevent auto-reconnect
                    socket.close();
                }
                connectWebSocket();
            } else {
                // No saved session, start new one
                newChatBtn.click();
            }
        }
    } catch (e) {
        console.error('Failed to switch project:', e);
    }
}

async function loadChatHistory(sessionId) {
    messagesArea.innerHTML = '';
    activeAiMessage = null;
    resetTransientExecutionUI();
    
    try {
        const res = await fetch(`${API_BASE}/api/history/${sessionId}`);
        const history = await res.json();
        hasSentMessageInCurrentSession = history && history.length > 0;
        
        if (history.length === 0) {
            renderMessage({ type: 'ai', content: 'Chat started. How can I help you today?' });
            return;
        }
        
        history.forEach(msg => {
            renderMessage(msg);
        });
        
        // Scroll to bottom
        messagesArea.scrollTop = messagesArea.scrollHeight;
    } catch (e) {
        console.error('Failed to load history:', e);
        hasSentMessageInCurrentSession = false;
        renderMessage({ type: 'ai', content: 'Chat started. How can I help you today?' });
    }
}

function renderProjectFiles(files) {
    if (!projectFilesList) return;
    projectFilesList.innerHTML = '';
    
    files.forEach(file => {
        const item = document.createElement('div');
        item.className = 'flex items-center gap-2 p-2 bg-white border border-bordercolor rounded text-xs';
        item.innerHTML = `
            <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-gray-400"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            <span class="truncate flex-1">${file.name}</span>
        `;
        projectFilesList.appendChild(item);
    });
}

function renderProjectChats(chats) {
    if (!projectChatsList) return;
    projectChatsList.innerHTML = '';
    
    // Sort chats by created_at descending (newest first)
    const sortedChats = [...chats].sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
    
    sortedChats.forEach(chat => {
        const isActive = chat.id === currentSessionId;
        if (isActive) currentChatName = chat.name || '';
        const item = document.createElement('div');
        item.className = `group flex items-center gap-2 p-2 rounded text-xs cursor-pointer transition-colors ${
            isActive ? 'bg-anthropic text-white' : 'bg-white border border-bordercolor hover:bg-gray-50'
        }`;
        
        const date = chat.created_at ? new Date(chat.created_at * 1000).toLocaleDateString() : 'Unknown';
        
        item.innerHTML = `
            <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${isActive ? 3 : 2}" stroke-linecap="round" stroke-linejoin="round" class="${isActive ? 'text-white' : 'text-gray-400'}"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
            <span class="truncate flex-1 font-medium">${chat.name || 'Untitled'}</span>
            <div class="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                <button class="edit-chat-btn p-1 rounded-md hover:bg-white/20 text-current opacity-70 hover:opacity-100" title="Rename Chat">
                    <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>
                </button>
                <button class="delete-chat-btn p-1 rounded-md hover:bg-white/20 text-current opacity-70 hover:opacity-100" title="Delete Chat">
                    <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                </button>
            </div>
            <span class="opacity-60 text-[10px] whitespace-nowrap">${date}</span>
        `;
        
        item.querySelector('.edit-chat-btn').onclick = (e) => {
            e.stopPropagation();
            editChat(chat.id, chat.name);
        };
        item.querySelector('.delete-chat-btn').onclick = (e) => {
            e.stopPropagation();
            deleteChat(chat.id, chat.name);
        };
        
        item.onclick = () => switchChat(chat.id);
        projectChatsList.appendChild(item);
    });
}

async function switchChat(sessionId) {
    resetTransientExecutionUI();
    currentSessionId = sessionId;
    if (sessionIdEl) sessionIdEl.value = currentSessionId;
    switchView('chat');
    setWorkspaceVisibility();
    
    // Update mapping in localStorage
    if (hasSelectedProject && activeProjectId) {
        localStorage.setItem(`project_session_${activeProjectId}`, currentSessionId);
    }
    
    // Reload UI
    await loadChatHistory(sessionId);
    
    // Reconnect WebSocket to the correct thread
    if (socket) {
        socket.onclose = null; 
        socket.close();
    }
    connectWebSocket();
    
    // Refresh project details to update active chat highlighting
    const res = await fetch(`${API_BASE}/api/projects/${getEffectiveProjectId()}`);
    const project = await res.json();
    chatProjectIdForThread = getEffectiveProjectId();
    chatRegisteredInBackend = Boolean((project.chats || []).find((c) => c.id === sessionId));
    renderProjectChats(project.chats || []);
    currentChatName = (project.chats || []).find((c) => c.id === sessionId)?.name || '';
    renderWelcomeRecents();
}

async function editChat(chatId, currentName) {
    const newName = await showCustomInput('Rename Chat', 'Chat Name', currentName);
    if (!newName || newName === currentName) return;
    
    try {
        await fetch(`${API_BASE}/api/projects/${getEffectiveProjectId()}/chats/${chatId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: newName })
        });
        currentChatName = newName;
        switchProject(getEffectiveProjectId(), false);
    } catch (e) {
        console.error('Failed to rename chat:', e);
    }
}

async function deleteChat(chatId, chatName) {
    const confirmed = await showCustomConfirm('Delete Chat', `Are you sure you want to delete the chat "${chatName || 'Untitled'}"?`, true);
    if (!confirmed) return;
    
    try {
        await fetch(`${API_BASE}/api/projects/${getEffectiveProjectId()}/chats/${chatId}`, {
            method: 'DELETE'
        });
        switchProject(getEffectiveProjectId(), false);
        if (chatId === currentSessionId) {
             newChatBtn.click();
        }
    } catch (e) {
        console.error('Failed to delete chat:', e);
    }
}

async function maybeAutoNameCurrentChat(userText, fileNames = []) {
    if (!userText?.trim()) return;
    if (!isUntitledName(currentChatName)) return;
    if (titleGenerationInFlight) return;
    titleGenerationInFlight = true;

    try {
        await ensureChatRegistered();
        const projectId = getChatProjectId();

        // Ask small LLM for a title
        let title = '';
        try {
            const res = await fetch(API_BASE + '/api/chats/generate-title', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: userText, files: fileNames.map(n => ({ name: n })) })
            });
            const data = await res.json();
            title = (data?.title || '').trim().replace(/\s+/g, ' ').slice(0, 60);
        } catch (_) {}

        // Fallback to local heuristic
        if (!title) title = deriveChatTitle(userText);
        if (!title) return;

        // Save the title
        await fetch(`${API_BASE}/api/projects/${projectId}/chats/${currentSessionId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: title })
        });
        currentChatName = title;

        // Refresh sidebar
        await refreshSidebarRecents(projectId);
    } catch (e) {
        console.error('Auto-name failed:', e);
    } finally {
        titleGenerationInFlight = false;
    }
}

async function refreshSidebarRecents(projectId) {
    try {
        const res = await fetch(`${API_BASE}/api/projects/${projectId || getEffectiveProjectId()}`);
        const project = await res.json();
        cachedProjects = cachedProjects.map(p => p.id === project.id ? project : p);
        if (getEffectiveProjectId() === project.id) {
            renderProjectChats(project.chats || []);
        }
    } catch (_) {}
}

async function editProject(projectId, currentName) {
    const newName = await showCustomInput('Rename Project', 'Project Name', currentName);
    if (!newName || newName === currentName) return;
    
    try {
        await fetch(`${API_BASE}/api/projects/${projectId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: newName })
        });
        loadProjects();
    } catch (e) {
        console.error('Failed to rename project:', e);
    }
}

async function deleteProject(projectId, projectName) {
    const confirmed = await showCustomConfirm('Delete Project', `Are you sure you want to delete the project "${projectName}"? This will delete associated workspace files.`, true);
    if (!confirmed) return;
    
    try {
        const res = await fetch(`${API_BASE}/api/projects/${projectId}`, {
            method: 'DELETE'
        });
        const data = await res.json();
        if (data.status === 'ok') {
             if (projectId === activeProjectId) {
                  activeProjectId = null;
                  hasSelectedProject = false;
                  currentChatName = '';
                  localStorage.removeItem('active_project_id');
                  setWorkspaceVisibility();
                  switchView('projects');
                  renderProjectInspector(null);
                  renderWelcomeRecents();
                  loadProjects();
             } else {
                  loadProjects();
             }
        } else {
             alert(data.message || 'Failed to delete project');
        }
    } catch (e) {
        console.error('Failed to delete project:', e);
    }
}


async function handleCreateProject() {
    const name = await showCustomInput('New Project', 'Project Name');
    if (!name) return;
    
    const instructions = await showCustomInput('Project Details', 'Project Instructions (optional)');
    
    try {
        const res = await fetch(API_BASE + '/api/projects', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, instructions })
        });
        const newProject = await res.json();
        await loadProjects();
        switchProject(newProject.id);
        switchView('chat');
    } catch (e) {
        console.error('Failed to create project:', e);
    }
}

addProjectBtn?.addEventListener('click', handleCreateProject);
document.getElementById('addProjectViewBtn')?.addEventListener('click', handleCreateProject);

// ─── Event Listeners ────────────────────────────────────────────────────────

openSettingsBtn?.addEventListener('click', () => {
    settingsModal.classList.remove('hidden');
    settingsModal.classList.add('flex');
    loadSettingsData();
});

closeSettingsBtn?.addEventListener('click', () => {
    settingsModal.classList.add('hidden');
    settingsModal.classList.remove('flex');
});
closeSettingsFooterBtn?.addEventListener('click', () => {
    settingsModal.classList.add('hidden');
    settingsModal.classList.remove('flex');
});

// Close modal when clicking outside content
settingsModal?.addEventListener('click', (e) => {
    if (e.target === settingsModal) {
        settingsModal.classList.add('hidden');
        settingsModal.classList.remove('flex');
    }
});

// ===== SETTINGS TABS FUNCTIONALITY =====
const settingsTabs = document.querySelectorAll('.settings-tab');
const tabContents = document.querySelectorAll('.settings-tab-content, .tab-content');

settingsTabs.forEach(tab => {
    tab.addEventListener('click', () => {
        const tabName = tab.getAttribute('data-tab');
        
        // Remove active class from all tabs and contents
        settingsTabs.forEach(t => t.classList.remove('active'));
        tabContents.forEach(c => c.classList.remove('active'));
        
        // Add active class to clicked tab and corresponding content
        tab.classList.add('active');
        // Support both old and new class names
        const content = document.querySelector(`.settings-tab-content[data-tab="${tabName}"]`)
            || document.querySelector(`.tab-content[data-tab="${tabName}"]`);
        content?.classList.add('active');
        
        // Refresh memory data when Memory tab is opened
        if (tabName === 'memory') {
            loadMemoryTabData();
        }
    });
});

// Set first tab as active on load
if (settingsTabs.length > 0) {
    settingsTabs[0].classList.add('active');
}
if (tabContents.length > 0) {
    tabContents[0].classList.add('active');
}

// Function to refresh just the memory tab data
async function loadMemoryTabData() {
    try {
        const [topicsRes, interestsRes, conversationsRes, memoriesRes] = await Promise.all([
            fetch(API_BASE + '/api/topics').catch(() => null),
            fetch(API_BASE + '/api/interests').catch(() => null),
            fetch(API_BASE + '/api/conversations').catch(() => null),
            fetch(API_BASE + '/api/memories')
        ]);
        
        const topicsData = topicsRes ? await topicsRes.json() : { topics: [] };
        const interestsData = interestsRes ? await interestsRes.json() : { interests: [] };
        const conversationsData = conversationsRes ? await conversationsRes.json() : { conversations: [] };
        const memories = await memoriesRes.json();
        
        renderTrackedTopics(topicsData.topics || []);
        renderDetectedInterests(interestsData.interests || []);
        renderRecentConversations(conversationsData.conversations || []);
        renderMemories(memories);
        
        if (memoriesCountEl) memoriesCountEl.innerText = memories.length || 0;
    } catch (e) {
        console.error('Failed to refresh memory tab data:', e);
    }
}

// ===== SYSTEM PROMPT =====
const systemPromptInput = document.getElementById('systemPromptInput');
const customInstructionsInput = document.getElementById('customInstructionsInput');
const saveSystemPromptBtn = document.getElementById('saveSystemPromptBtn');
const resetSystemPromptBtn = document.getElementById('resetSystemPromptBtn');

const DEFAULT_SYSTEM_PROMPT = `You are Owlynn, a helpful AI assistant built on LangGraph. You have access to tools for:
- Executing code in a sandboxed environment
- Reading and writing files in the workspace
- Searching the web
- Managing long-term memory
- Processing various file formats (JSON, YAML, PDF, etc.)

Be clear, concise, and helpful. When using tools, explain what you're doing. Break down complex problems into steps.`;

resetSystemPromptBtn?.addEventListener('click', () => {
    if (confirm('Reset to default system prompt?')) {
        systemPromptInput.value = DEFAULT_SYSTEM_PROMPT;
    }
});

saveSystemPromptBtn?.addEventListener('click', async () => {
    const data = {
        system_prompt: systemPromptInput.value,
        custom_instructions: customInstructionsInput.value,
        name: personaNameInput.value,
        tone: personaToneInput.value
    };
    try {
        const res = await fetch(API_BASE + '/api/system-settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        alert('System settings saved!');
    } catch (e) {
        console.error('Failed to save system settings:', e);
        alert('Failed to save settings');
    }
});

// ===== MEMORY TOGGLES =====
const shortTermMemoryToggle = document.getElementById('shortTermMemoryToggle');
const longTermMemoryToggle = document.getElementById('longTermMemoryToggle');

shortTermMemoryToggle?.addEventListener('change', async (e) => {
    try {
        await fetch(API_BASE + '/api/memory-settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ short_term_enabled: e.target.checked })
        });
    } catch (err) {
        console.error('Failed to update short-term memory setting:', err);
    }
});

longTermMemoryToggle?.addEventListener('change', async (e) => {
    try {
        await fetch(API_BASE + '/api/memory-settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ long_term_enabled: e.target.checked })
        });
    } catch (err) {
        console.error('Failed to update long-term memory setting:', err);
    }
});

// ===== ADVANCED SETTINGS =====
const temperatureSlider = document.getElementById('temperatureSlider');
const temperatureValue = document.getElementById('temperatureValue');
const topPSlider = document.getElementById('topPSlider');
const topPValue = document.getElementById('topPValue');
const maxTokensSlider = document.getElementById('maxTokensSlider');
const maxTokensValue = document.getElementById('maxTokensValue');
const topKSlider = document.getElementById('topKSlider');
const topKValue = document.getElementById('topKValue');
const streamingToggle = document.getElementById('streamingToggle');
const thinkingToggle = document.getElementById('thinkingToggle');
const toolVisibilityToggle = document.getElementById('toolVisibilityToggle');
const saveAdvancedBtn = document.getElementById('saveAdvancedBtn');

// Update slider display values
temperatureSlider?.addEventListener('input', (e) => {
    temperatureValue.textContent = parseFloat(e.target.value).toFixed(1);
});

topPSlider?.addEventListener('input', (e) => {
    topPValue.textContent = parseFloat(e.target.value).toFixed(2);
});

maxTokensSlider?.addEventListener('input', (e) => {
    maxTokensValue.textContent = parseInt(e.target.value);
});

topKSlider?.addEventListener('input', (e) => {
    topKValue.textContent = parseInt(e.target.value);
});

saveAdvancedBtn?.addEventListener('click', async () => {
    const data = {
        temperature: parseFloat(temperatureSlider.value),
        top_p: parseFloat(topPSlider.value),
        max_tokens: parseInt(maxTokensSlider.value),
        top_k: parseInt(topKSlider.value),
        streaming_enabled: streamingToggle.checked,
        show_thinking: thinkingToggle.checked,
        show_tool_execution: toolVisibilityToggle.checked
    };
    try {
        await fetch(API_BASE + '/api/advanced-settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        alert('Advanced settings saved!');
    } catch (e) {
        console.error('Failed to save advanced settings:', e);
        alert('Failed to save settings');
    }
});

saveProfileBtn?.addEventListener('click', async () => {
    const data = {
        name: profileNameInput?.value,
        preferred_language: profileLangInput?.value,
        response_style: profileStyleInput?.value,
        llm_base_url: profileLlmUrlInput?.value,
        llm_model_name: profileLlmModelInput?.value,
        small_llm_base_url: document.getElementById('profileSmallLlmUrl')?.value,
        small_llm_model_name: document.getElementById('profileSmallLlmModel')?.value,
        large_llm_base_url: document.getElementById('profileLargeLlmUrl')?.value,
        large_llm_model_name: document.getElementById('profileLargeLlmModel')?.value,
    };
    // Remove undefined/null entries
    Object.keys(data).forEach(k => { if (data[k] == null) delete data[k]; });
    try {
        await fetch(API_BASE + '/api/profile', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        // Update welcome heading
        const welcomeH = document.getElementById('welcomeHeading');
        if (welcomeH && data.name) welcomeH.textContent = `Welcome, ${data.name}`;
        const profileDisp = document.getElementById('profileNameDisplay');
        if (profileDisp && data.name) profileDisp.textContent = data.name;
        updateComposerStyleQuickLabel();
        alert('Profile saved!');
    } catch (e) {
        console.error(e);
    }
});

savePersonaBtn?.addEventListener('click', async () => {
    const data = {
        name: personaNameInput.value,
        tone: personaToneInput.value
    };
    try {
        const res = await fetch(API_BASE + '/api/persona', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        const persona = await res.json();
        if (agentNameDisplay) agentNameDisplay.innerHTML = `
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-anthropic"><path d="M12 2a8 8 0 0 0-8 8c0 5.4 7.05 11.5 7.35 11.76a1 1 0 0 0 1.3 0C12.95 21.5 20 15.4 20 10a8 8 0 0 0-8-8z"/><circle cx="12" cy="10" r="3"/></svg>
            ${persona.name || 'Owlynn'}
        `;
        alert('Persona saved!');
    } catch (e) {
        console.error(e);
    }
});

chatForm.addEventListener('submit', handleSend);
messageInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend(e);
    }
});

messageInput.addEventListener('input', function() {
    this.style.height = '56px';
    this.style.height = (this.scrollHeight) + 'px';
});

newChatBtn.addEventListener('click', async () => {
    // Reset reasoning state
    updateAgentStatus('idle');

    const keepCurrentDraft =
        !hasSentMessageInCurrentSession &&
        isUntitledName(currentChatName) &&
        currentSessionId && socket;

    if (!keepCurrentDraft) {
        currentSessionId = generateUUID();
        currentChatName = 'Untitled';
        hasSentMessageInCurrentSession = false;
        chatRegisteredInBackend = false;
        titleGenerationInFlight = false;
        // "General" chats start unassigned (default project) until you explicitly switch/attach.
        chatProjectIdForThread = currentView === 'welcome' ? 'default' : getEffectiveProjectId();
        if (sessionIdEl) sessionIdEl.value = currentSessionId;
    }

    messagesArea.innerHTML = '';
    resetTransientExecutionUI();
    pendingFiles = [];
    renderPreviews();
    
    // Start as untitled/floating chat. It can be auto-renamed from the first user message.
    const chatName = 'Untitled';
    
    // Save mapping to localStorage (draft sessions too, so switching projects can restore them)
    if (chatProjectIdForThread) {
        localStorage.setItem(`project_session_${chatProjectIdForThread}`, currentSessionId);
    }

    if (!keepCurrentDraft) {
        if (socket) {
            socket.onclose = null; // Prevent auto-reconnect
            socket.close();
        }
        connectWebSocket();
    } else {
        // Make sure the websocket is connected to the draft thread.
        if (!socket || socket.readyState !== WebSocket.OPEN || websocketThreadId !== currentSessionId) {
            if (socket) {
                socket.onclose = null;
                socket.close();
            }
            connectWebSocket();
        }
    }
    switchView('welcome');
    setWorkspaceVisibility();
});

// Mode Toggle Listeners
modeFastBtn?.addEventListener('click', () => {
    activeMode = 'tools_off';
    updateModeUI();
});

modeReasoningBtn?.addEventListener('click', () => {
    activeMode = 'tools_on';
    updateModeUI();
});

function updateModeUI() {
    if (!modeFastBtn || !modeReasoningBtn) return;
    if (activeMode === 'tools_off') {
        modeFastBtn.className = 'px-3 py-1 font-medium bg-anthropic text-white transition-colors';
        modeReasoningBtn.className = 'px-3 py-1 font-medium text-gray-500 hover:bg-gray-50 transition-colors';
    } else {
        modeFastBtn.className = 'px-3 py-1 font-medium text-gray-500 hover:bg-gray-50 transition-colors';
        modeReasoningBtn.className = 'px-3 py-1 font-medium bg-anthropic text-white transition-colors';
    }
}

attachBtn?.addEventListener('click', () => fileInput?.click());

fileInput.addEventListener('change', (e) => processFiles(e.target.files));

// ─── Drag and Drop ──────────────────────────────────────────────────────────
// ─── Drag and Drop (Chat Attachments) ───────────────────────────────────────
chatContainer.addEventListener('dragenter', (e) => {
    e.preventDefault();
    const types = e.dataTransfer.types;
    if (types.includes('Files') || types.includes('application/json')) {
        dragOverlay.classList.remove('hidden');
        dragOverlay.classList.add('flex');
    }
});

chatContainer.addEventListener('dragover', (e) => {
    e.preventDefault();
});

chatContainer.addEventListener('dragleave', (e) => {
    // Only hide when truly leaving the chat container bounds
    if (!e.relatedTarget || !chatContainer.contains(e.relatedTarget)) {
        dragOverlay.classList.add('hidden');
        dragOverlay.classList.remove('flex');
    }
});

function handleAttachmentDrop(e) {
    e.preventDefault();
    dragOverlay.classList.add('hidden');
    dragOverlay.classList.remove('flex');
    
    // Check for Workspace Drag Reference
    const workspaceData = e.dataTransfer.getData('application/json');
    if (workspaceData) {
        try {
            const file = JSON.parse(workspaceData);
            if (file.source === 'workspace') {
                processWorkspaceFileToChat(file);
                return;
            }
        } catch (err) {
            console.error('Failed to parse workspace drop:', err);
        }
    }
    
    processFiles(e.dataTransfer.files);
}

dragOverlay.addEventListener('drop', handleAttachmentDrop);
chatContainer.addEventListener('drop', handleAttachmentDrop);
welcomePane?.addEventListener('drop', handleAttachmentDrop);

if (welcomePane) {
    welcomePane.addEventListener('dragenter', (e) => {
        e.preventDefault();
        const types = e.dataTransfer.types;
        if (types.includes('Files') || types.includes('application/json')) {
            dragOverlay.classList.remove('hidden');
            dragOverlay.classList.add('flex');
        }
    });
    
    welcomePane.addEventListener('dragover', (e) => {
        e.preventDefault();
    });
    
    welcomePane.addEventListener('dragleave', (e) => {
        if (!e.relatedTarget || !welcomePane.contains(e.relatedTarget)) {
            dragOverlay.classList.add('hidden');
            dragOverlay.classList.remove('flex');
        }
    });
}

// Helper for adding Workspace file references to Chat Attachments
function processWorkspaceFileToChat(file) {
    const fileItem = {
        name: file.name,
        type: 'workspace_ref', // Mark as internal reference
        path: file.path, 
        size: 0, 
        base64: "" // Safe loaded bypass
    };
    pendingFiles.push(fileItem);
    renderPreviews();
}

// WebSocket Logic
function connectWebSocket() {
    updateConnectionStatus('connecting');
    
    websocketThreadId = currentSessionId;
    socket = new WebSocket(`${WS_BASE}/ws/chat/${currentSessionId}`);
    
    socket.onopen = () => {
        updateConnectionStatus('connected');
    };
    
    socket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        
        if (data.type === 'status') {
            updateAgentStatus(data.content);
        } else if (data.type === 'file_status') {
            loadWorkspaceFiles(); // Live refresh Workspace panel lists on updates
        } else if (data.type === 'tool_execution') {
            // Handle tool execution display
            handleToolExecution(data);
        } else if (data.type === 'interrupt') {
            handleSecurityInterrupt(data.interrupts || []);
        } else if (data.type === 'model_info') {
            // Track which model was used
            currentModelUsed = data.model || 'unknown';
        } else if (data.type === 'message') {
            renderMessage(data.message);
        } else if (data.type === 'chunk') {
            handleChunk(data.content, data.metadata);
        } else if (data.type === 'error') {
            renderErrorUI(data.content, data.title, data.details);
            updateAgentStatus('idle');
        } else if (data.type === 'debug') {
            console.log('[Server Debug]', data.content);
        }
    };
    
    socket.onclose = (event) => {
        console.log(`[WS Check] Closed. Code: ${event.code}, Reason: ${event.reason || 'None'}`);
        resetTransientExecutionUI();
        updateConnectionStatus('disconnected');
        // Auto reconnect after 3 seconds
        setTimeout(connectWebSocket, 3000);
    };
    
    socket.onerror = (error) => {
        try {
            console.error('[WS Check] Error Details:', JSON.stringify(error, Object.getOwnPropertyNames(error)));
        } catch (e) {
            console.error('[WS Check] Error:', error);
        }
    };
}

// Handle tool execution events
function handleToolExecution(data) {
    const { tool_name, status, input, output, error, duration, tool_call_id } = data;
    const toolKey = tool_call_id || `tool:${tool_name || 'unknown'}`;

    if (status === 'running') {
        activeToolName = tool_name || null;
        showThinkingIndicator();
        updateThinkingIndicatorText();
    } else if (activeToolName && tool_name && activeToolName === tool_name) {
        activeToolName = null;
        updateThinkingIndicatorText();
    }
    
    let wrapper = messagesArea.lastElementChild;
    if (!wrapper || !['agent', 'agent-thinking'].includes(wrapper.dataset.sender)) {
        wrapper = document.createElement('div');
        wrapper.className = 'flex gap-4 group-msg mb-6';
        wrapper.dataset.sender = 'agent';
        
        const avatar = document.createElement('div');
        avatar.className = 'w-8 h-8 rounded shrink-0 bg-anthropic flex items-center justify-center text-white mt-1';
        avatar.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 8V4H8"/><rect x="4" y="8" width="16" height="12" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/></svg>';
        wrapper.appendChild(avatar);
        
        const contentDiv = document.createElement('div');
        contentDiv.className = 'flex-1 message-content text-base text-textdark';
        wrapper.appendChild(contentDiv);
        messagesArea.appendChild(wrapper);
    }
    wrapper.dataset.sender = 'agent';

    if (thinkingIndicatorEl && thinkingIndicatorEl === wrapper) {
        clearThinkingIndicator();
        wrapper = null;
    }

    if (!wrapper) {
        wrapper = document.createElement('div');
        wrapper.className = 'flex gap-4 group-msg mb-6';
        wrapper.dataset.sender = 'agent';

        const avatar = document.createElement('div');
        avatar.className = 'w-8 h-8 rounded shrink-0 bg-anthropic flex items-center justify-center text-white mt-1';
        avatar.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 8V4H8"/><rect x="4" y="8" width="16" height="12" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/></svg>';
        wrapper.appendChild(avatar);

        const contentDiv = document.createElement('div');
        contentDiv.className = 'flex-1 message-content text-base text-textdark';
        wrapper.appendChild(contentDiv);
        messagesArea.appendChild(wrapper);
    }

    const contentDiv = wrapper.querySelector('.message-content');
    const toolCard = renderToolExecution(tool_name, status, input, output, error);
    
    if (duration) {
        const durationEl = document.createElement('div');
        durationEl.className = 'text-xs text-gray-400 mt-2';
        durationEl.textContent = `⏱ ${duration.toFixed(2)}s`;
        toolCard.appendChild(durationEl);
    }

    if (liveToolCards.has(toolKey)) {
        const existingCard = liveToolCards.get(toolKey);
        existingCard.replaceWith(toolCard);
    } else {
        insertAgentToolCard(contentDiv, toolCard);
    }
    if (status === 'running') {
        liveToolCards.set(toolKey, toolCard);
    } else {
        liveToolCards.delete(toolKey);
    }
    moveActiveAnswerToEnd();
    scrollToBottom();
}

function _safeToolArgsPreview(args) {
    try {
        if (typeof args === 'string') return args.slice(0, 200);
        return JSON.stringify(args).slice(0, 200);
    } catch (_) {
        return '[unavailable]';
    }
}

async function showSecurityApprovalConfirm(interruptPayload) {
    const calls = Array.isArray(interruptPayload?.sensitive_tool_calls) ? interruptPayload.sensitive_tool_calls : [];
    const toolNames = calls.map((c) => String(c?.name || 'unknown_tool'));
    const summary = toolNames.length > 0
        ? `Sensitive action requested for: ${toolNames.join(', ')}`
        : 'Sensitive action requested.';

    const details = calls.length > 0
        ? `\n\nDetails:\n${calls.map((c) => `- ${c.name}: ${_safeToolArgsPreview(c.args)}`).join('\n')}`
        : '';

    return new Promise((resolve) => {
        const modal = document.getElementById('customConfirmModal');
        const titleEl = document.getElementById('confirmModalTitle');
        const messageEl = document.getElementById('confirmModalMessage');
        const confirmBtn = document.getElementById('confirmConfirmBtn');
        const cancelBtn = document.getElementById('cancelConfirmBtn');

        if (!modal || !titleEl || !messageEl || !confirmBtn || !cancelBtn) {
            resolve(confirm(`${summary}\n\nApprove to continue?`));
            return;
        }

        titleEl.textContent = 'Approve Sensitive Tool Action';
        messageEl.textContent = `${summary}${details}\n\nApprove to continue, or cancel to deny.`;
        confirmBtn.className = "px-4 py-2 rounded-xl text-sm bg-anthropic text-white hover:bg-opacity-90 transition-opacity font-medium";
        confirmBtn.textContent = "Approve";
        cancelBtn.textContent = "Deny";

        modal.classList.remove('hidden');
        modal.classList.add('flex');

        const cleanup = (result) => {
            modal.classList.add('hidden');
            modal.classList.remove('flex');
            confirmBtn.onclick = null;
            cancelBtn.onclick = null;
            cancelBtn.textContent = "Cancel";
            resolve(result);
        };

        confirmBtn.onclick = () => cleanup(true);
        cancelBtn.onclick = () => cleanup(false);
    });
}

async function handleSecurityInterrupt(interrupts) {
    const first = Array.isArray(interrupts) && interrupts.length > 0 ? interrupts[0] : null;
    if (!first || typeof first !== 'object') return;

    // Handle ask_user interrupts (agent asking a clarifying question)
    if (first.type === 'ask_user' || first.question) {
        handleAskUserInterrupt(first);
        return;
    }

    activeToolName = null;
    showThinkingIndicator();
    const textEl = thinkingIndicatorEl?.querySelector('#thinkingText');
    if (textEl) textEl.textContent = 'Waiting for approval to run sensitive action...';

    const approved = await showSecurityApprovalConfirm(first);
    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'security_approval', approved: Boolean(approved) }));
    }
}

function handleAskUserInterrupt(payload) {
    resetTransientExecutionUI();
    const question = payload.question || 'The agent needs more information to continue.';
    const choices = Array.isArray(payload.choices) ? payload.choices.slice(0, 3) : [];

    const wrapper = document.createElement('div');
    wrapper.className = 'flex gap-4 group-msg mb-6';
    wrapper.dataset.sender = 'ai';

    const avatar = document.createElement('div');
    avatar.className = 'w-8 h-8 rounded shrink-0 bg-anthropic flex items-center justify-center text-white mt-1';
    avatar.textContent = '🦉';
    wrapper.appendChild(avatar);

    const contentDiv = document.createElement('div');
    contentDiv.className = 'flex-1';

    const card = document.createElement('div');
    card.className = 'ask-user-card';

    // Header
    let html = `
        <div class="flex items-center gap-2 mb-3 text-sm font-medium" style="color: var(--owl-accent);">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
            Owlynn needs your input
        </div>
        <p class="text-sm mb-3" style="color: var(--owl-text);">${escapeHtml(question)}</p>`;

    // Choice buttons (1-3)
    if (choices.length > 0) {
        html += `<div class="ask-user-choices" style="display:flex;flex-wrap:wrap;gap:0.5rem;margin-bottom:0.75rem;">`;
        choices.forEach((c, i) => {
            html += `<button class="ask-choice-btn" onclick="submitAskUserChoice('${escapeHtml(c)}')" style="padding:0.4rem 0.8rem;border-radius:0.5rem;font-size:0.85rem;font-weight:500;background:var(--accent-soft);border:1px solid rgba(199,154,59,0.4);color:#f6e2b4;cursor:pointer;transition:all 0.15s;">${escapeHtml(c)}</button>`;
        });
        html += `</div>`;
    }

    // Free text input (always present)
    html += `
        <div class="flex gap-2">
            <input type="text" class="flex-1 px-3 py-2 rounded-lg text-sm border outline-none focus:ring-1 focus:ring-[var(--owl-accent)]" placeholder="${choices.length > 0 ? 'Or type your own answer...' : 'Type your answer...'}" id="askUserInput" />
            <button onclick="submitAskUserResponse()" class="px-4 py-2 rounded-lg text-sm font-medium transition-colors" style="background:var(--accent-soft);border:1px solid rgba(199,154,59,0.4);color:#f6e2b4;">Send</button>
        </div>`;

    card.innerHTML = html;
    contentDiv.appendChild(card);
    wrapper.appendChild(contentDiv);
    messagesArea.appendChild(wrapper);
    scrollToBottom(true);

    setTimeout(() => {
        const input = document.getElementById('askUserInput');
        if (input) {
            input.focus();
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') submitAskUserResponse();
            });
        }
    }, 100);
}

function submitAskUserChoice(choice) {
    _sendAskUserAnswer(choice);
}

function submitAskUserResponse() {
    const input = document.getElementById('askUserInput');
    if (!input) return;
    const answer = input.value.trim();
    if (!answer) return;
    _sendAskUserAnswer(answer);
}

function _sendAskUserAnswer(answer) {
    // Disable all inputs and buttons in the ask-user card
    const card = document.querySelector('.ask-user-card');
    if (card) {
        card.querySelectorAll('input, button').forEach(el => { el.disabled = true; });
        // Show what was selected
        const feedback = document.createElement('div');
        feedback.className = 'text-xs mt-2';
        feedback.style.color = 'var(--owl-accent)';
        feedback.textContent = `✓ ${answer}`;
        card.appendChild(feedback);
    }
    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'ask_user_response', answer }));
    }
}

// Render error with better styling
function renderErrorUI(message, title = 'Error', details = null) {
    resetTransientExecutionUI();
    const wrapper = document.createElement('div');
    wrapper.className = 'flex gap-4 group-msg mb-6';
    wrapper.dataset.sender = 'error';
    
    const avatar = document.createElement('div');
    avatar.className = 'w-8 h-8 rounded shrink-0 bg-red-500 flex items-center justify-center text-white mt-1';
    avatar.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>';
    wrapper.appendChild(avatar);
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'flex-1';
    contentDiv.appendChild(renderErrorMessage(title, message, details));
    wrapper.appendChild(contentDiv);
    
    messagesArea.appendChild(wrapper);
    scrollToBottom();
}

// UI Updaters
function quickAction(text) {
    if (!messageInput || !chatForm) return;
    messageInput.value = text;
    // Trigger input event to resize textarea
    messageInput.dispatchEvent(new Event('input'));
    // Small delay to ensure resize finished
    setTimeout(() => {
        chatForm.dispatchEvent(new Event('submit'));
    }, 10);
}

function updateConnectionStatus(status) {
    if (status === 'connected') {
        statusDot.className = 'w-2 h-2 rounded-full bg-green-500';
        if (mobileDot) mobileDot.className = 'w-2 h-2 rounded-full bg-green-500';
        statusText.textContent = 'Connected';
        sendBtn.disabled = false;
    } else if (status === 'connecting') {
        statusDot.className = 'w-2 h-2 rounded-full bg-yellow-500 hover:animate-pulse';
        if (mobileDot) mobileDot.className = 'w-2 h-2 rounded-full bg-yellow-500 hover:animate-pulse';
        statusText.textContent = 'Connecting...';
        sendBtn.disabled = true;
    } else {
        statusDot.className = 'w-2 h-2 rounded-full bg-red-500';
        if (mobileDot) mobileDot.className = 'w-2 h-2 rounded-full bg-red-500';
        statusText.textContent = 'Disconnected';
        sendBtn.disabled = true;
    }
}

function updateAgentStatus(status) {
    if (status === 'idle') {
        isReasoning = false;
        resetTransientExecutionUI();
        agentStatus.textContent = 'Waiting for input...';
        agentStatus.className = 'mt-2 text-xs font-mono text-gray-400';
        sendBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>';
        sendBtn.title = "Send message";
        
        finalizeActiveMessage();
    } else {
        isReasoning = true;
        showThinkingIndicator();
        updateThinkingIndicatorText();
        agentStatus.textContent = 'Agent is reasoning...';
        agentStatus.className = 'mt-2 text-xs font-mono text-anthropic animate-pulse';
        // Display a STOP Square button next to or inside the action scope
        sendBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="text-anthropic cursor-pointer hover:text-red-500"><rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/></svg>';
        sendBtn.title = "Stop Generating";
        sendBtn.disabled = false; // Ensure click is enabled for Stop
    }
}

async function ensureChatRegistered() {
    if (chatRegisteredInBackend) return;
    if (!currentSessionId) return;

    const projectId = getChatProjectId();
    if (!projectId) return;

    const nameForRegistration = isUntitledName(currentChatName) ? 'Untitled' : (currentChatName || 'Untitled');

    try {
        await fetch(`${API_BASE}/api/projects/${projectId}/chats`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: currentSessionId, name: nameForRegistration })
        });

        chatRegisteredInBackend = true;
        localStorage.setItem(`project_session_${projectId}`, currentSessionId);

        // Refresh cached project so recents updates across views
        const res = await fetch(`${API_BASE}/api/projects/${projectId}`);
        const project = await res.json();
        cachedProjects = cachedProjects.map((p) => (p.id === projectId ? project : p));

        // Only re-render the sidebar recents if this chat belongs to the project currently being shown.
        const sidebarProjectId = getEffectiveProjectId();
        if (sidebarProjectId === projectId) {
            if (projectChatsSection) projectChatsSection.classList.remove('hidden');
            renderProjectChats(project.chats || []);
            renderProjectInspector(project);
        }
        renderWelcomeRecents();
    } catch (e) {
        console.error('Failed to register chat with project:', e);
    }
}

// ─── File Handling ──────────────────────────────────────────────────────────
function processFiles(fileList) {
    Array.from(fileList).forEach(file => {
        const reader = new FileReader();
        reader.onload = (e) => {
            const dataUrl = e.target.result;
            // Strip the data URL prefix to get raw base64
            const base64 = dataUrl.split(',')[1];
            const fileObj = { name: file.name, type: file.type || 'application/octet-stream', data: base64 };
            
            // Image preview
            if (file.type.startsWith('image/')) {
                fileObj.preview = dataUrl;
            }
            
            pendingFiles.push(fileObj);
            renderPreviews();
        };
        reader.readAsDataURL(file);
    });
}

function renderPreviews() {
    const renderInto = (containerEl) => {
        if (!containerEl) return;
        containerEl.innerHTML = '';
        if (pendingFiles.length === 0) {
            containerEl.classList.add('hidden');
            return;
        }
        containerEl.classList.remove('hidden');
        containerEl.className = 'flex flex-wrap gap-2 mb-2';
        
        pendingFiles.forEach((f, idx) => {
            const chip = document.createElement('div');
            chip.className = 'relative flex items-center gap-2 bg-cloud border border-bordercolor rounded-lg px-3 py-1.5 text-sm';
            
            if (f.preview) {
                const img = document.createElement('img');
                img.src = f.preview;
                img.className = 'w-8 h-8 object-cover rounded';
                chip.appendChild(img);
            } else if (f.type === 'workspace_ref') {
                // Workspace File Icon
                const icon = document.createElement('div');
                icon.className = 'w-8 h-8 rounded bg-orange-50 flex items-center justify-center text-orange-600';
                icon.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 22h16a2 2 0 0 0 2-2V7.5L14.5 2H6a2 2 0 0 0-2 2v4"/><polyline points="14 2 14 8 20 8"/></svg>';
                chip.appendChild(icon);
                chip.classList.add('border-orange-200', 'bg-orange-50/50');
            } else {
                // File type icon
                const icon = document.createElement('div');
                icon.className = 'w-8 h-8 rounded bg-gray-200 flex items-center justify-center text-gray-600';
                icon.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';
                chip.appendChild(icon);
            }
            
            const name = document.createElement('span');
            name.className = 'max-w-[120px] truncate text-gray-700';
            name.textContent = f.name;
            chip.appendChild(name);
            
            // Remove button
            const removeBtn = document.createElement('button');
            removeBtn.type = 'button';
            removeBtn.className = 'ml-1 text-gray-400 hover:text-red-500 transition-colors';
            removeBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
            removeBtn.addEventListener('click', () => {
                pendingFiles.splice(idx, 1);
                renderPreviews();
            });
            chip.appendChild(removeBtn);
            
            containerEl.appendChild(chip);
        });
    };
    
    renderInto(attachmentPreviews);
    renderInto(welcomeAttachmentPreviews);
}

/**
 * Flatten API/stream content (string | blocks | nested objects) to plain text for markdown.
 * Avoids "[object Object]" when providers nest { text: { ... } } or table-like blocks.
 */
function flattenAiContentForUi(content) {
    if (content == null || content === undefined) return '';
    if (typeof content === 'string') return content;
    if (typeof content === 'number' || typeof content === 'boolean') return String(content);
    if (Array.isArray(content)) {
        return content.map(flattenAiContentForUi).join('');
    }
    if (typeof content === 'object') {
        if (content.text != null) return flattenAiContentForUi(content.text);
        if (content.content != null) return flattenAiContentForUi(content.content);
        if (content.delta != null) return flattenAiContentForUi(content.delta);
        if (content.value != null) return flattenAiContentForUi(content.value);
        const type = content.type;
        if (type === 'text' && content.text != null) return flattenAiContentForUi(content.text);
        try {
            return JSON.stringify(content);
        } catch (_) {
            return '';
        }
    }
    return '';
}

/** LLM stream chunks may be a string or LangChain-style content blocks. */
function normalizeStreamChunk(chunk) {
    return flattenAiContentForUi(chunk);
}

function handleChunk(chunkText, metadata = {}) {
    chunkText = normalizeStreamChunk(chunkText);
    clearThinkingIndicator();
    if (!activeAiMessage) {
        const lastWrapper = messagesArea.lastElementChild;
        let wrapper, contentDiv;
        
        if (lastWrapper && lastWrapper.dataset.sender === 'agent') {
            wrapper = lastWrapper;
            contentDiv = wrapper.querySelector('.message-content');
        } else {
            wrapper = document.createElement('div');
            wrapper.className = 'flex gap-4 group-msg mb-6';
            wrapper.dataset.sender = 'agent';
            
            const avatar = document.createElement('div');
            avatar.className = 'w-8 h-8 rounded shrink-0 bg-anthropic flex items-center justify-center text-white mt-1';
            avatar.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8V4H8"/><rect x="4" y="8" width="16" height="12" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/></svg>';
            wrapper.appendChild(avatar);
            
            contentDiv = document.createElement('div');
            contentDiv.className = 'flex-1 message-content text-base text-textdark leading-relaxed space-y-4';
            wrapper.appendChild(contentDiv);
            messagesArea.appendChild(wrapper);
        }
        
        const mainContainer = document.createElement('div');
        mainContainer.className = 'agent-final-answer';
        contentDiv.appendChild(mainContainer);
        
        activeAiMessage = {
            wrapper: wrapper,
            contentDiv: contentDiv,
            mainContainer: mainContainer,
            buffer: "",
            insideThought: false,
            thoughtContainer: null,
            mainText: "",
            thoughtText: ""
        };
    }
    moveActiveAnswerToEnd();

    activeAiMessage.buffer += chunkText;
    let buf = activeAiMessage.buffer;

    // Handle <think>...</think> tags (Qwen3.5 reasoning format) — suppress from display
    if (!activeAiMessage.insideThought && buf.includes('<think>')) {
        const idx = buf.indexOf('<think>');
        const textBefore = buf.substring(0, idx);
        if (textBefore) {
            if (!activeAiMessage.mainContainer) {
                activeAiMessage.mainContainer = document.createElement('div');
                activeAiMessage.contentDiv.appendChild(activeAiMessage.mainContainer);
            }
            activeAiMessage.mainText += textBefore;
            activeAiMessage.mainContainer.innerHTML = marked.parse(activeAiMessage.mainText);
        }
        activeAiMessage.insideThought = true;
        activeAiMessage._thinkTagMode = true; // track that we're in <think> not <thought>
        activeAiMessage.buffer = buf.substring(idx + 7); // len('<think>') = 7
        activeAiMessage.thoughtText = '';
        return;
    }
    if (activeAiMessage._thinkTagMode && activeAiMessage.insideThought) {
        if (buf.includes('</think>')) {
            const idx = buf.indexOf('</think>');
            activeAiMessage.insideThought = false;
            activeAiMessage._thinkTagMode = false;
            activeAiMessage.buffer = buf.substring(idx + 8); // len('</think>') = 8
            return handleChunk('');
        }
        // Still inside <think> — swallow the content silently
        activeAiMessage.buffer = '';
        return;
    }

    if (!activeAiMessage.insideThought && buf.includes('<thought>')) {
        const idx = buf.indexOf('<thought>');
        const textBefore = buf.substring(0, idx);
        if (textBefore) {
            if (!activeAiMessage.mainContainer) {
                activeAiMessage.mainContainer = document.createElement('div');
                activeAiMessage.contentDiv.appendChild(activeAiMessage.mainContainer);
            }
            activeAiMessage.mainText += textBefore;
            activeAiMessage.mainContainer.innerHTML = marked.parse(activeAiMessage.mainText);
        }
        activeAiMessage.insideThought = true;
        activeAiMessage.buffer = buf.substring(idx + 9);
        
        const details = document.createElement('details');
        details.className = 'mb-4 bg-gray-50 border border-bordercolor rounded-lg overflow-hidden';
        details.open = true;
        
        const summary = document.createElement('summary');
        summary.className = 'px-4 py-2 text-sm font-medium text-gray-700 cursor-pointer hover:bg-gray-100 flex items-center gap-2';
        summary.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-anthropic transition-transform duration-200"><polyline points="6 9 12 15 18 9"/></svg> Thinking Process`;
        
        const thoughtContent = document.createElement('div');
        thoughtContent.className = 'p-4 text-sm text-gray-600 border-t border-bordercolor';
        
        details.appendChild(summary);
        details.appendChild(thoughtContent);
        
        // Append details element
        if (activeAiMessage.mainContainer) {
             activeAiMessage.contentDiv.insertBefore(details, activeAiMessage.mainContainer);
        } else {
             activeAiMessage.contentDiv.appendChild(details);
        }
        
        activeAiMessage.thoughtContainer = thoughtContent;
        return handleChunk(""); 
    }
    
    if (activeAiMessage.insideThought && buf.includes('</thought>')) {
        const idx = buf.indexOf('</thought>');
        const textBefore = buf.substring(0, idx);
        if (textBefore) {
            activeAiMessage.thoughtText += textBefore;
            activeAiMessage.thoughtContainer.innerHTML = marked.parse(activeAiMessage.thoughtText);
        }
        activeAiMessage.insideThought = false;
        activeAiMessage.buffer = buf.substring(idx + 10);
        
        // Close details
        if (activeAiMessage.thoughtContainer && activeAiMessage.thoughtContainer.parentElement) {
            activeAiMessage.thoughtContainer.parentElement.open = false;
        }
        
        return handleChunk("");
    }

    // --- GLM Adaptive Fallback (Robust token-split search) ---
    const fullTextSearch = activeAiMessage.mainText + buf;
    if (fullTextSearch.includes('<|begin_of_box|>')) {
        const idx = fullTextSearch.indexOf('<|begin_of_box|>');
        const textBefore = fullTextSearch.substring(0, idx);
        
        if (activeAiMessage.insideThought) {
            // Unlikely to hit if insideThought, but safe fallback
            activeAiMessage.thoughtText += textBefore;
            activeAiMessage.insideThought = false;
        } else {
            // Everything before <|begin_of_box|> is Thought!
            activeAiMessage.thoughtText = (activeAiMessage.thoughtText || "") + textBefore;
        }
        
        // Clear mainText so answer doesn't append to thought
        activeAiMessage.mainText = "";
        if (activeAiMessage.mainContainer) activeAiMessage.mainContainer.innerHTML = "";
        
        if (!activeAiMessage.thoughtContainer) {
            const details = document.createElement('details');
            details.className = 'mb-4 bg-gray-50 border border-bordercolor rounded-lg overflow-hidden';
            details.open = false; 
            
            const summary = document.createElement('summary');
            summary.className = 'px-4 py-2 text-sm font-medium text-gray-700 cursor-pointer hover:bg-gray-100 flex items-center gap-2';
            summary.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-anthropic transition-transform duration-200"><polyline points="6 9 12 15 18 9"/></svg> Thinking Process`;
            
            const thoughtContent = document.createElement('div');
            thoughtContent.className = 'p-4 text-sm text-gray-600 border-t border-bordercolor';
            
            details.appendChild(summary);
            details.appendChild(thoughtContent);
            
            activeAiMessage.contentDiv.insertBefore(details, activeAiMessage.contentDiv.firstChild);
            activeAiMessage.thoughtContainer = thoughtContent;
        }
        activeAiMessage.thoughtContainer.innerHTML = marked.parse(activeAiMessage.thoughtText);
        
        // Update buffer to rest of text after <|begin_of_box|>
        activeAiMessage.buffer = fullTextSearch.substring(idx + 16);
        return handleChunk(""); 
    }

    if (fullTextSearch.includes('<|end_of_box|>')) {
        const idx = fullTextSearch.indexOf('<|end_of_box|>');
        const textBefore = fullTextSearch.substring(0, idx);
        if (textBefore) {
            if (!activeAiMessage.mainContainer) {
                activeAiMessage.mainContainer = document.createElement('div');
                activeAiMessage.contentDiv.appendChild(activeAiMessage.mainContainer);
            }
            // textBefore contains correct relative text
            activeAiMessage.mainText = textBefore; 
            activeAiMessage.mainContainer.innerHTML = marked.parse(activeAiMessage.mainText);
        }
        activeAiMessage.buffer = fullTextSearch.substring(idx + 14);
        return handleChunk("");
    }

    if (activeAiMessage.insideThought) {
        if (activeAiMessage.buffer) {
            activeAiMessage.thoughtText += activeAiMessage.buffer;
            activeAiMessage.thoughtContainer.innerHTML = marked.parse(activeAiMessage.thoughtText);
            activeAiMessage.buffer = "";
        }
    } else {
        if (activeAiMessage.buffer) {
            if (!activeAiMessage.mainContainer) {
                activeAiMessage.mainContainer = document.createElement('div');
                activeAiMessage.contentDiv.appendChild(activeAiMessage.mainContainer);
            }
            activeAiMessage.mainText += activeAiMessage.buffer;
            activeAiMessage.mainContainer.innerHTML = marked.parse(activeAiMessage.mainText);
            activeAiMessage.buffer = "";
        }
    }

    scrollToBottom();
}

function finalizeActiveMessage() {
    if (activeAiMessage) {
        addMessageActions(activeAiMessage.contentDiv, activeAiMessage.mainText || activeAiMessage.thoughtText, activeAiMessage.wrapper);
        activeAiMessage = null;
        // Scroll to bottom after finalizing — tool call cards may have pushed the answer up
        setTimeout(scrollToBottom, 50);
    }
}

function addMessageActions(contentDiv, textContent, wrapper) {
    if (contentDiv.querySelector('.message-actions')) return; 

    const actionsDiv = document.createElement('div');
    actionsDiv.className = 'flex flex-col gap-2 mt-3 pt-2 border-t border-gray-100';
    
    // Show style badge instead of model badge for cleaner UX.
    const styleMap = {
        normal: 'Normal',
        learning: 'Learning',
        concise: 'Concise',
        explanatory: 'Explanatory',
        formal: 'Formal',
    };
    const infoBadge = document.createElement('div');
    infoBadge.className = 'model-info-badge';
    infoBadge.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 20h16"/><path d="M6 16l4-8 4 6 2-3 2 5"/></svg> <span>Style: ${DOMPurify.sanitize(styleMap[responseStyle] || 'Normal')}</span>`;
    actionsDiv.appendChild(infoBadge);
    
    const buttonsDiv = document.createElement('div');
    buttonsDiv.className = 'flex gap-2 message-actions';
    
    const copyBtn = document.createElement('button');
    copyBtn.className = 'text-xs flex items-center gap-1 text-gray-400 hover:text-black transition-colors';
    copyBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> Copy`;
    copyBtn.addEventListener('click', () => {
         navigator.clipboard.writeText(textContent);
         const original = copyBtn.innerHTML;
         copyBtn.innerHTML = `✅ Copied`;
         setTimeout(() => copyBtn.innerHTML = original, 2000);
    });
    
    const regenBtn = document.createElement('button');
    regenBtn.className = 'text-xs flex items-center gap-1 text-gray-400 hover:text-black transition-colors';
    regenBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg> Regenerate`;
    regenBtn.addEventListener('click', () => {
         if (lastHumanMessage) {
              if (wrapper) wrapper.remove();
              socket.send(JSON.stringify(buildChatWsPayload(lastHumanMessage, [])));
         }
    });

    buttonsDiv.appendChild(copyBtn);
    buttonsDiv.appendChild(regenBtn);
    actionsDiv.appendChild(buttonsDiv);
    contentDiv.appendChild(actionsDiv);
}
async function handleSend(e) {
    if (e) e.preventDefault();

    if (isReasoning) {
        stopLlm();
        return;
    }
    
    const text = messageInput.value.trim();
    if ((!text && pendingFiles.length === 0) || socket.readyState !== WebSocket.OPEN) return;

    // Register this thread once so it shows up in recents/history views.
    await ensureChatRegistered();

    if (text) {
        maybeAutoNameCurrentChat(text, pendingFiles.map(f => f.name));
    }
    
    // Optimistic UI
    renderUserMessage(text, pendingFiles);
    lastHumanMessage = text; // Remember for regenerate
    
    // Send to backend with files and current mode
    socket.send(JSON.stringify(buildChatWsPayload(
        text,
        pendingFiles.map(f => ({ name: f.name, type: f.type, data: f.data, path: f.path }))
    )));
    hasSentMessageInCurrentSession = true;

    
    // Clear
    messageInput.value = '';
    messageInput.style.height = '56px';
    pendingFiles = [];
    renderPreviews();
    fileInput.value = '';
}

function stopLlm() {
    if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'stop' }));
        activeToolName = null;
        showThinkingIndicator();
        const textEl = thinkingIndicatorEl?.querySelector('#thinkingText');
        if (textEl) textEl.textContent = 'Stopping generation...';
    }
}

function renderUserMessage(text, files = []) {
    const wrapper = document.createElement('div');
    wrapper.className = 'flex justify-end mb-6';
    wrapper.dataset.sender = 'human';
    
    const inner = document.createElement('div');
    inner.className = 'flex flex-col items-end gap-2 max-w-[85%]';
    
    // Show attached file previews
    if (files && files.length > 0) {
        const fileRow = document.createElement('div');
        fileRow.className = 'flex flex-wrap gap-2 justify-end';
        files.forEach(f => {
            const chip = document.createElement('div');
            chip.className = 'flex items-center gap-1.5 bg-userbubble border border-bordercolor px-2 py-1 rounded-lg text-xs text-gray-600';
            if (f.preview) {
                const img = document.createElement('img');
                img.src = f.preview;
                img.className = 'w-6 h-6 object-cover rounded';
                chip.appendChild(img);
            }
            const span = document.createElement('span');
            span.textContent = f.name;
            chip.appendChild(span);
            fileRow.appendChild(chip);
        });
        inner.appendChild(fileRow);
    }
    
    if (text) {
        let cleanedText = text;
        const foundFiles = [];

        if (typeof text === 'string') {
            const fileRegex = /\[File:\s+([^\]]+)\]\s*[\r\n]+```[\s\S]*?```/g;
            let match;
            while ((match = fileRegex.exec(text)) !== null) {
                foundFiles.push(match[1]);
            }
            if (foundFiles.length > 0) {
                cleanedText = text.replace(fileRegex, '').trim();
                
                const fileRow = document.createElement('div');
                fileRow.className = 'flex flex-wrap gap-2 justify-end mb-1';
                foundFiles.forEach(name => {
                    const chip = document.createElement('div');
                    chip.className = 'flex items-center gap-1.5 bg-userbubble border border-bordercolor px-2 py-1 rounded-lg text-xs text-gray-600';
                    chip.innerHTML = `📄 <span>${name}</span>`;
                    fileRow.appendChild(chip);
                });
                inner.appendChild(fileRow);
            }
        }

        if (cleanedText || Array.isArray(text)) {
            const bubble = document.createElement('div');
            bubble.className = 'bg-userbubble text-textdark px-5 py-3.5 rounded-[1.15rem] text-[15px] leading-relaxed border border-bordercolor/60 shadow-[0_8px_20px_rgba(2,8,22,0.24)] relative group';
            
            const textSpan = document.createElement('span');
            if (typeof text === 'string') {
                textSpan.textContent = cleanedText;
            } else if (Array.isArray(text)) {
                // Find the text part in multimodal content
                const textPart = text.find(p => p.type === 'text');
                textSpan.textContent = textPart ? textPart.text : '[Multimodal Content]';
            }

        
        const editBtn = document.createElement('button');
        editBtn.className = 'absolute -left-6 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 transition-opacity text-gray-400 hover:text-black';
        editBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>';
        
        editBtn.addEventListener('click', () => {
            const originalText = textSpan.textContent;
            bubble.innerHTML = '';
            
            const textarea = document.createElement('textarea');
            textarea.className = 'w-full bg-transparent resize-none focus:outline-none text-base border-b border-gray-400 mb-2';
            textarea.value = originalText;
            textarea.rows = 1;
            bubble.appendChild(textarea);
            
            const controls = document.createElement('div');
            controls.className = 'flex gap-2 justify-end';
            
            const cancelBtn = document.createElement('button');
            cancelBtn.className = 'text-xs px-2 py-1 bg-gray-200 rounded hover:bg-gray-300';
            cancelBtn.textContent = 'Cancel';
            
            const saveBtn = document.createElement('button');
            saveBtn.className = 'text-xs px-2 py-1 bg-anthropic text-white rounded hover:opacity-90';
            saveBtn.textContent = 'Save';
            
            controls.appendChild(cancelBtn);
            controls.appendChild(saveBtn);
            bubble.appendChild(controls);
            textarea.focus();
            
            cancelBtn.addEventListener('click', () => {
                bubble.innerHTML = '';
                bubble.appendChild(textSpan);
                bubble.appendChild(editBtn);
            });
            
            saveBtn.addEventListener('click', () => {
                const newText = textarea.value.trim();
                if (newText && newText !== originalText) {
                    textSpan.textContent = newText;
                    lastHumanMessage = newText;
                    
                    // Clear following DOM elements
                    let sibling = wrapper.nextSibling;
                    while (sibling) {
                        const next = sibling.nextSibling;
                        sibling.remove();
                        sibling = next;
                    }
                    
                    // Resubmit
                    messageInput.value = newText;
                    chatForm.dispatchEvent(new Event('submit'));
                } else {
                    bubble.innerHTML = '';
                    bubble.appendChild(textSpan);
                    bubble.appendChild(editBtn);
                }
            });
        });

        bubble.appendChild(textSpan);
        bubble.appendChild(editBtn);
        inner.appendChild(bubble);
    }
    }
    
    wrapper.appendChild(inner);
    messagesArea.appendChild(wrapper);
    scrollToBottom(true);
}

function renderMessage(msg) {
    if (msg.type === 'ai' || msg.type === 'tool') {
        clearThinkingIndicator();
    }
    if (msg.type === 'human') {
        renderUserMessage(msg.content);
        return;
    }

    // Guard up-front: skip messages with no useful content at all
    const flatContent = flattenAiContentForUi(msg.content);
    const hasContent = flatContent && flatContent.trim();
    const hasToolCalls = msg.tool_calls && msg.tool_calls.length > 0;
    if (msg.type === 'ai' && !hasContent && !hasToolCalls) return;
    if (msg.type === 'tool' && !msg.content) return;

    // Final model reply after tools: backend now sends this even when stream events were missed.
    if (msg.type === 'ai' && hasContent && !hasToolCalls && activeAiMessage?.contentDiv) {
        const sanitized = flatContent
            .replace(/```(?:json)?\s*\{[^}]*\}\s*```/gs, '')
            .replace(/```(?:json)?\s*```/g, '')
            .trim();
        if (sanitized) {
            if (!activeAiMessage.mainContainer) {
                const mc = document.createElement('div');
                mc.className = 'agent-final-answer';
                activeAiMessage.contentDiv.appendChild(mc);
                activeAiMessage.mainContainer = mc;
            }
            activeAiMessage.mainText = sanitized;
            activeAiMessage.mainContainer.innerHTML = marked.parse(sanitized);
            moveActiveAnswerToEnd();
            finalizeActiveMessage();
            scrollToBottom();
            return;
        }
    }

    // --- Message Grouping Logic ---
    // We group AI messages and Tool results into the same visual block if they are consecutive.
    const lastWrapper = messagesArea.lastElementChild;
    let contentContainer = null;
    let isNewGroup = true;

    if (lastWrapper && lastWrapper.dataset.sender === 'agent' && (msg.type === 'ai' || msg.type === 'tool')) {
        contentContainer = lastWrapper.querySelector('.message-content');
        isNewGroup = false;
    }

    if (isNewGroup) {
        const wrapper = document.createElement('div');
        wrapper.className = 'flex gap-4 group-msg mb-6';
        wrapper.dataset.sender = (msg.type === 'ai' || msg.type === 'tool') ? 'agent' : 'human';

        // Avatar
        const avatar = document.createElement('div');
        avatar.className = 'w-8 h-8 rounded shrink-0 bg-anthropic flex items-center justify-center text-white mt-1';
        avatar.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8V4H8"/><rect x="4" y="8" width="16" height="12" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/></svg>';
        wrapper.appendChild(avatar);

        // Content Container
        contentContainer = document.createElement('div');
        contentContainer.className = 'flex-1 message-content text-base text-textdark leading-relaxed space-y-4';
        wrapper.appendChild(contentContainer);
        
        messagesArea.appendChild(wrapper);
    }

    // --- Content Rendering ---
    if (msg.type === 'ai') {
        // Reorder: tool plan / calls first, brief pre-tool text next, final answer comes last via stream or merge above
        if (hasToolCalls) {
            if (!contentContainer.querySelector('.agent-process-label')) {
                const lab = document.createElement('div');
                lab.className = 'agent-process-label text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2';
                lab.textContent = 'Tools & sources';
                contentContainer.appendChild(lab);
            }
            msg.tool_calls.forEach(tc => {
                const toolDiv = createToolCallUI(tc);
                contentContainer.appendChild(toolDiv);
            });
        }

        if (hasContent) {
            const textDiv = document.createElement('div');
            // Strip any residual ```json ... ``` fences
            const sanitized = flatContent
                .replace(/```(?:json)?\s*\{[^}]*\}\s*```/gs, '')
                .replace(/```(?:json)?\s*```/g, '')
                .trim();
            if (sanitized) {
                if (!hasToolCalls) {
                    const existingFinal = contentContainer.querySelector('.agent-final-answer');
                    if (existingFinal && (existingFinal.textContent || '').trim().length > 24) {
                        scrollToBottom();
                        return;
                    }
                }
                if (hasToolCalls) {
                    textDiv.className = 'text-sm text-gray-600 mb-2 border-l-2 border-gray-200 pl-3';
                } else {
                    textDiv.classList.add('agent-final-answer', 'mt-4', 'pt-3', 'border-t', 'border-bordercolor');
                }
                textDiv.innerHTML = marked.parse(sanitized);
                contentContainer.appendChild(textDiv);
                if (!hasToolCalls) {
                    const groupWrapper = contentContainer.closest('.group-msg');
                    if (groupWrapper) {
                        addMessageActions(textDiv, sanitized, groupWrapper);
                    }
                }
            }
        }
    } else if (msg.type === 'tool') {
        // Tool Result
        const container = document.createElement('div');
        container.className = 'mt-2 border border-bordercolor rounded-lg overflow-hidden max-w-2xl';
        
        const header = document.createElement('div');
        header.className = 'bg-gray-50 px-4 py-2 flex items-center justify-between cursor-pointer hover:bg-gray-100 transition-colors border-b border-bordercolor';
        
        const headerTitle = document.createElement('div');
        headerTitle.className = 'flex items-center gap-2 text-xs font-semibold text-green-600 uppercase tracking-wider';
        headerTitle.innerHTML = `
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
            Output [${msg.tool_name || 'Tool'}]
        `;
        
        const arrow = document.createElement('div');
        arrow.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-gray-400 transition-transform duration-200 transform"><polyline points="6 9 12 15 18 9"/></svg>';
        
        header.appendChild(headerTitle);
        header.appendChild(arrow);
        
        const body = document.createElement('div');
        body.className = 'bg-white p-4 hidden';
        
        const pre = document.createElement('pre');
        pre.className = 'text-xs font-mono text-gray-600 m-0 p-0 bg-transparent overflow-x-auto whitespace-pre-wrap';
        
        const out = flattenAiContentForUi(msg.content);
        pre.textContent = out.length > 3000 ? out.substring(0, 3000) + '\n\n... (truncated for display)' : out;
        
        body.appendChild(pre);
        container.appendChild(header);
        container.appendChild(body);
        
        // Toggle Logic
        let isExpanded = false;
        header.addEventListener('click', () => {
            isExpanded = !isExpanded;
            body.classList.toggle('hidden', !isExpanded);
            arrow.querySelector('svg').classList.toggle('rotate-180', isExpanded);
        });
        
        contentContainer.appendChild(container);
    }
    
    scrollToBottom();
}

function createToolCallUI(tc) {
    const container = document.createElement('div');
    container.className = 'mt-3 mb-1 border border-bordercolor rounded-lg overflow-hidden max-w-2xl';
    
    const header = document.createElement('div');
    header.className = 'bg-cloud px-4 py-2 flex items-center justify-between cursor-pointer hover:bg-gray-100 transition-colors';
    
    const title = document.createElement('div');
    title.className = 'flex items-center gap-2 text-sm font-medium text-gray-700';
    title.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-anthropic"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>
        Using tool <code class="bg-white border border-gray-200 px-1.5 py-0.5 rounded ml-1 text-xs text-anthropic">${tc.name}</code>
    `;
    
    const arrow = document.createElement('div');
    arrow.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-gray-400 transition-transform duration-200 transform rotate-180"><polyline points="6 9 12 15 18 9"/></svg>';
    
    header.appendChild(title);
    header.appendChild(arrow);
    
    const body = document.createElement('div');
    body.className = 'bg-white p-4 border-t border-bordercolor hidden';
    
    const pre = document.createElement('pre');
    pre.className = 'text-xs font-mono text-gray-600 m-0 p-0 bg-transparent overflow-x-auto';
    pre.textContent = JSON.stringify(tc.args, null, 2);
    
    body.appendChild(pre);
    
    // Toggle Logic
    let isExpanded = false;
    header.addEventListener('click', () => {
        isExpanded = !isExpanded;
        if(isExpanded) {
            body.classList.remove('hidden');
            arrow.querySelector('svg').classList.remove('rotate-180');
        } else {
            body.classList.add('hidden');
            arrow.querySelector('svg').classList.add('rotate-180');
        }
    });
    
    container.appendChild(header);
    container.appendChild(body);
    return container;
}

function renderError(err) {
    renderErrorUI(err || 'An unexpected error occurred', 'Error');
}

// Helpers
function generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        var r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

function scrollToBottom(force = false) {
    if (!chatContainer) return;
    // Only auto-scroll if user is near the bottom (within 150px) or forced
    const distFromBottom = chatContainer.scrollHeight - chatContainer.scrollTop - chatContainer.clientHeight;
    if (force || distFromBottom < 150) {
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }
}

// Custom Confirm Modal Helper
function showCustomConfirm(title, message, isDanger = false) {
    return new Promise((resolve) => {
        const modal = document.getElementById('customConfirmModal');
        const titleEl = document.getElementById('confirmModalTitle');
        const messageEl = document.getElementById('confirmModalMessage');
        const confirmBtn = document.getElementById('confirmConfirmBtn');
        const cancelBtn = document.getElementById('cancelConfirmBtn');

        if (!modal || !titleEl || !messageEl || !confirmBtn || !cancelBtn) {
            console.error('Custom Confirm Modal elements not found');
            resolve(confirm(message)); 
            return;
        }

        titleEl.textContent = title;
        messageEl.textContent = message;

        if (isDanger) {
            confirmBtn.className = "px-4 py-2 rounded-xl text-sm bg-red-500 text-white hover:bg-red-600 transition-colors font-medium";
            confirmBtn.textContent = "Delete";
        } else {
            confirmBtn.className = "px-4 py-2 rounded-xl text-sm bg-anthropic text-white hover:bg-opacity-90 transition-opacity font-medium";
            confirmBtn.textContent = "Confirm";
        }

        modal.classList.remove('hidden');
        modal.classList.add('flex');

        const cleanup = (result) => {
            modal.classList.add('hidden');
            modal.classList.remove('flex');
            confirmBtn.onclick = null;
            cancelBtn.onclick = null;
            resolve(result);
        };

        confirmBtn.onclick = () => cleanup(true);
        cancelBtn.onclick = () => cleanup(false);
    });
}

// Custom Input Modal Helper
function showCustomInput(title, label, defaultValue = '') {
    return new Promise((resolve) => {
        const modal = document.getElementById('customInputModal');
        const titleEl = document.getElementById('customInputTitle');
        const labelEl = document.getElementById('customInputLabel');
        const inputEl = document.getElementById('customInputField');
        const confirmBtn = document.getElementById('confirmCustomInputBtn');
        const cancelBtn = document.getElementById('cancelCustomInputBtn');
        const closeBtn = document.getElementById('closeCustomInputBtn');

        if (!modal || !titleEl || !labelEl || !inputEl || !confirmBtn || !cancelBtn || !closeBtn) {
            console.error('Custom Input Modal elements not found');
            resolve(prompt(label, defaultValue)); // Fallback
            return;
        }

        titleEl.textContent = title;
        labelEl.textContent = label;
        inputEl.value = defaultValue;
        
        modal.classList.remove('hidden');
        modal.classList.add('flex');
        
        // Timeout to ensure display is applied before focus
        setTimeout(() => {
            inputEl.focus();
            inputEl.select();
        }, 10);

        const cleanup = () => {
            modal.classList.add('hidden');
            modal.classList.remove('flex');
            confirmBtn.onclick = null;
            cancelBtn.onclick = null;
            closeBtn.onclick = null;
            inputEl.onkeydown = null;
            modal.onclick = null;
        };

        const handleConfirm = () => {
            const value = inputEl.value;
            cleanup();
            resolve(value);
        };

        const handleCancel = () => {
            cleanup();
            resolve(null);
        };

        confirmBtn.onclick = handleConfirm;
        cancelBtn.onclick = handleCancel;
        closeBtn.onclick = handleCancel;

        modal.onclick = (e) => {
            if (e.target === modal) handleCancel();
        };

        inputEl.onkeydown = (e) => {
            if (e.key === 'Enter') handleConfirm();
            if (e.key === 'Escape') handleCancel();
        };
    });
}

// ─── Workspace File Explorer Panel ──────────────────────────────────────────
async function loadWorkspaceFiles() {
    const listEl = document.getElementById('workspaceFilesList');
    if (!listEl) return;
    if (!hasSelectedProject) {
        listEl.innerHTML = '<p class="text-xs text-gray-400 italic text-center py-8">Select a project to open workspace files.</p>';
        return;
    }
    
    try {
        const res = await fetch(`${API_BASE}/api/files?sub_path=${encodeURIComponent(currentSubPath)}&project_id=${getEffectiveProjectId()}`);
        const files = await res.json();
        renderWorkspaceFiles(files);
        renderBreadcrumbs();
    } catch (e) {
        console.error('Failed to load workspace files:', e);
    }
}

function renderBreadcrumbs() {
    const breadcrumbs = document.getElementById('workspaceBreadcrumbs');
    if (!breadcrumbs) return;
    
    breadcrumbs.innerHTML = '<span class="cursor-pointer hover:text-black font-medium text-gray-700" onclick="navigateToFolder(\'\')">Workspace</span>';
    
    if (currentSubPath) {
        const parts = currentSubPath.split('/').filter(p => p);
        let pathAccum = '';
        parts.forEach(part => {
            pathAccum += (pathAccum ? '/' : '') + part;
            const currentPath = pathAccum; // Capture closed scope
            breadcrumbs.innerHTML += `
                <span class="text-gray-400">/</span>
                <span class="cursor-pointer hover:text-black" onclick="navigateToFolder('${currentPath.replace(/'/g, "\\'")}')">${part}</span>
            `;
        });
    }
}

function navigateToFolder(path) {
    currentSubPath = path;
    loadWorkspaceFiles();
}

function renderWorkspaceFiles(files) {
    const listEl = document.getElementById('workspaceFilesList');
    if (!listEl) return;
    listEl.innerHTML = '';
    
    if (files.length === 0) {
        listEl.innerHTML = '<p class="text-xs text-gray-400 italic text-center py-8">No files in workspace.</p>';
        return;
    }
    
    files.forEach(file => {
        const item = document.createElement('div');
        item.className = 'group flex items-center justify-between gap-2 p-2.5 bg-gray-50 border border-bordercolor rounded-xl text-xs hover:border-anthropic/30 hover:bg-white transition-all';
        item.dataset.filename = file.name;
        
        // Make draggable only for files
        if (file.type === 'file') {
             item.setAttribute('draggable', 'true');
             item.classList.add('cursor-grab', 'active:cursor-grabbing');
             item.addEventListener('dragstart', (e) => {
                 e.dataTransfer.setData('application/json', JSON.stringify({
                     source: 'workspace',
                     name: file.name,
                     path: currentSubPath ? `${currentSubPath}/${file.name}` : file.name
                 }));
             });
        } else if (file.type === 'folder') {
             item.classList.add('cursor-pointer');
             item.onclick = () => navigateToFolder(currentSubPath ? `${currentSubPath}/${file.name}` : file.name);
             
             // Move Drag-Drop support into folder items
             item.addEventListener('dragover', (e) => {
                 e.preventDefault();
                 item.classList.add('bg-yellow-50/50', 'border-yellow-200');
             });
             item.addEventListener('dragleave', () => {
                 item.classList.remove('bg-yellow-50/50', 'border-yellow-200');
             });
             item.addEventListener('drop', async (e) => {
                 e.preventDefault();
                 item.classList.remove('bg-yellow-50/50', 'border-yellow-200');
                 const data = e.dataTransfer.getData('application/json');
                 if (data) {
                      try {
                          const dragItem = JSON.parse(data);
                          if (dragItem.source === 'workspace' && dragItem.name !== file.name) {
                               await moveWorkspaceFile(dragItem.name, dragItem.path, currentSubPath ? `${currentSubPath}/${file.name}` : file.name);
                          }
                      } catch(err) {}
                 }
             });
        }
        
        const isProcessing = file.status === 'processing';
        const isProcessed = file.status === 'processed';
        const isFolder = file.type === 'folder';
        
        item.innerHTML = `
            <div class="flex items-center gap-2 flex-1 min-w-0 pointer-events-none">
                <div class="p-1.5 rounded-lg ${isFolder ? 'bg-yellow-50 text-yellow-600' : 'bg-gray-100 text-gray-500'}">
                    ${isFolder ? 
                       '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/></svg>' :
                       '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>'
                    }
                </div>
                <div class="flex-1 min-w-0">
                    <p class="font-medium text-gray-800 truncate" title="${file.name}">${file.name}</p>
                    <p class="text-[10px] text-gray-400">${isFolder ? 'Folder' : formatBytes(file.size)} ${!isFolder ? '• ' + new Date(file.modified * 1000).toLocaleDateString() : ''}</p>
                </div>
                <div class="status-badge">
                    ${isProcessing && !isFolder ? '<span class="flex h-2 w-2 relative"><span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-yellow-400 opacity-75"></span><span class="relative inline-flex rounded-full h-2 w-2 bg-yellow-500"></span></span>' : ''}
                    ${isProcessed && !isFolder ? '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="text-green-500"><polyline points="20 6 9 17 4 12"/></svg>' : ''}
                </div>
            </div>
            <div class="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                ${!isFolder ? `
                <button class="view-file-btn p-1 rounded-md hover:bg-gray-100 text-gray-400 hover:text-black" title="View">
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0z"/><circle cx="12" cy="12" r="3"/></svg>
                </button>
                ` : ''}
                <button class="rename-file-btn p-1 rounded-md hover:bg-gray-100 text-gray-400 hover:text-anthropic" title="Rename">
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>
                </button>
                <button class="delete-file-btn p-1 rounded-md hover:bg-gray-100 text-gray-400 hover:text-red-500" title="Delete">
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                </button>
            </div>
        `;
        
        const viewBtn = item.querySelector('.view-file-btn');
        if (viewBtn) viewBtn.onclick = (e) => { e.stopPropagation(); viewWorkspaceFile(file.name); };
        item.querySelector('.rename-file-btn').onclick = (e) => { e.stopPropagation(); renameWorkspaceFile(file.name); };
        item.querySelector('.delete-file-btn').onclick = (e) => { e.stopPropagation(); deleteWorkspaceFile(file.name); };
        
        listEl.appendChild(item);
    });
}

async function deleteWorkspaceFile(name) {
    const confirmed = await showCustomConfirm('Delete File', `Are you sure you want to delete "${name}" from the workspace?`, true);
    if (!confirmed) return;
    try {
        await fetch(`${API_BASE}/api/files/${encodeURIComponent(name)}?sub_path=${encodeURIComponent(currentSubPath)}&project_id=${getEffectiveProjectId()}`, { method: 'DELETE' });
        loadWorkspaceFiles();
    } catch (e) {
        console.error('Failed to delete file:', e);
    }
}

async function renameWorkspaceFile(name) {
    const newName = await showCustomInput('Rename File', 'New Name', name);
    if (!newName || newName === name) return;
    try {
        await fetch(`${API_BASE}/api/files/${encodeURIComponent(name)}/rename`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ new_name: newName, sub_path: currentSubPath, project_id: getEffectiveProjectId() })
        });
        loadWorkspaceFiles();
    } catch (e) {
        console.error('Failed to rename file:', e);
    }
}

async function moveWorkspaceFile(filename, fullSrcPath, targetSubPath) {
    try {
        let current_sub = "";
        if (fullSrcPath.includes('/')) {
             current_sub = fullSrcPath.substring(0, fullSrcPath.lastIndexOf('/'));
        }
        await fetch(`${API_BASE}/api/files/${encodeURIComponent(filename)}/move`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                 current_sub_path: current_sub, 
                 target_sub_path: targetSubPath, 
                 project_id: getEffectiveProjectId() 
            })
        });
        loadWorkspaceFiles();
    } catch (e) {
        console.error('Move failed:', e);
    }
}

function formatBytes(bytes, decimals = 2) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

// Bind direct upload buttons
const uploadWorkspaceBtn = document.getElementById('uploadWorkspaceBtn');
const workspaceFileInput = document.getElementById('workspaceFileInput');

uploadWorkspaceBtn?.addEventListener('click', () => workspaceFileInput?.click());

workspaceFileInput?.addEventListener('change', async (e) => {
    if (e.target.files.length === 0) return;

    for (const file of e.target.files) {
        const formData = new FormData();
        formData.append('file', file);

        try {
            await fetch(`${API_BASE}/api/upload?sub_path=${encodeURIComponent(currentSubPath)}&project_id=${getEffectiveProjectId()}`, { method: 'POST', body: formData });
        } catch (err) {
            console.error('Upload failed:', err);
        }
    }
    loadWorkspaceFiles(); // Refresh
});

// Bind specialized Drag & Drop on Workspace Explorer Panel
const workspacePanel = document.getElementById('workspacePanel');
const workspaceDropZone = document.getElementById('workspaceDropZone');
let workspaceDragCounter = 0; // Fixes nested bubbling locks

if (workspacePanel && workspaceDropZone) {
    workspacePanel.addEventListener('dragenter', (e) => {
        e.preventDefault(); e.stopPropagation();
        if (e.dataTransfer.types.includes('Files')) {
            workspaceDragCounter++;
            workspaceDropZone.classList.remove('hidden');
        }
    });

    workspacePanel.addEventListener('dragover', (e) => {
        e.preventDefault(); e.stopPropagation();
    });

    workspacePanel.addEventListener('dragleave', (e) => {
        e.preventDefault(); e.stopPropagation();
        workspaceDragCounter--;
        if (workspaceDragCounter <= 0) {
            workspaceDropZone.classList.add('hidden');
        }
    });

    // Handle dragleave on dropzone as well to safeguard exiting
    workspaceDropZone.addEventListener('dragleave', (e) => {
        e.preventDefault(); e.stopPropagation();
        workspaceDragCounter = 0;
        workspaceDropZone.classList.add('hidden');
    });

    workspaceDropZone.addEventListener('drop', async (e) => {
        e.preventDefault(); e.stopPropagation();
        workspaceDragCounter = 0; // Reset
        workspaceDropZone.classList.add('hidden');
        
        const files = e.dataTransfer.files;
        if (!files.length) return;
        
        for (const file of files) {
            const formData = new FormData();
            formData.append('file', file);
            try {
                await fetch(`${API_BASE}/api/upload?sub_path=${encodeURIComponent(currentSubPath)}&project_id=${getEffectiveProjectId()}`, { method: 'POST', body: formData });
            } catch (err) {
                console.error('Upload failed:', err);
            }
        }
        loadWorkspaceFiles();
    });
}

// ─── Workspace File Viewer Modal ────────────────────────────────────────────
async function viewWorkspaceFile(name) {
    const modal = document.getElementById('fileViewerModal');
    const titleEl = document.getElementById('fileViewerTitle');
    const contentEl = document.getElementById('fileViewerContent');
    const downloadBtn = document.getElementById('downloadFileBtn');
    
    if (!modal || !contentEl) return;
    
    titleEl.textContent = name;
    contentEl.innerHTML = '<p class="text-xs text-gray-400 animate-pulse">Loading preview...</p>';
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    
    const fileUrl = `${API_BASE}/api/files/${encodeURIComponent(name)}?sub_path=${encodeURIComponent(currentSubPath)}&project_id=${getEffectiveProjectId()}`;
    downloadBtn.onclick = () => window.open(fileUrl, '_blank');
    
    const ext = name.split('.').pop().toLowerCase();
    
    if (ext === 'pdf') {
        contentEl.innerHTML = `<iframe src="${fileUrl}" class="w-full h-full border-0"></iframe>`;
    } else if (['png', 'jpg', 'jpeg', 'gif', 'svg'].includes(ext)) {
        contentEl.innerHTML = `<img src="${fileUrl}" class="max-w-full max-h-full object-contain p-4" />`;
    } else {
        try {
            const res = await fetch(fileUrl);
            const text = await res.text();
            contentEl.innerHTML = `<pre class="w-full h-full p-6 text-xs text-gray-700 font-mono bg-white overflow-auto whitespace-pre-wrap">${escapeHtml(text)}</pre>`;
        } catch (e) {
            contentEl.innerHTML = `<p class="text-red-500 text-xs">Failed to load content.</p>`;
        }
    }
}

function escapeHtml(text) {
    return text.replace(/[&<>"']/g, function(m) {
        return {
            '&': '&amp;', '<': '&lt;', '>': '&gt;',
            '"': '&quot;', "'": '&#039;'
        }[m];
    });
}

// Bind Viewer Modal Close Events
document.getElementById('closeFileViewerBtn')?.addEventListener('click', () => {
    const modal = document.getElementById('fileViewerModal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    document.getElementById('fileViewerContent').innerHTML = ''; // Clear iframe memory leaky
});

document.getElementById('fileViewerModal')?.addEventListener('click', (e) => {
    if (e.target === document.getElementById('fileViewerModal')) {
        const modal = document.getElementById('fileViewerModal');
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        document.getElementById('fileViewerContent').innerHTML = '';
    }
});

// ─── Workspace Resizable Sidebar ───────────────────────────────────────────
(function initWorkspaceResizer() {
    const handle = document.getElementById('workspaceResizeHandle');
    const panel = document.getElementById('workspacePanel');
    if (!handle || !panel) return;

    let isResizing = false;

    handle.addEventListener('mousedown', (e) => {
        isResizing = true;
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none'; // Prevent text selection
    });

    window.addEventListener('mousemove', (e) => {
        if (!isResizing) return;
        const offsetLeft = panel.getBoundingClientRect().left;
        const newWidth = e.clientX - offsetLeft;
        
        // Boundaries
        if (newWidth > 200 && newWidth < 600) {
             panel.style.width = `${newWidth}px`;
        }
    });

    window.addEventListener('mouseup', () => {
        if (isResizing) {
            isResizing = false;
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
        }
    });
})();

// ─── Workspace New Folder Toolbar Trigger ───────────────────────────────────
document.getElementById('newFolderBtn')?.addEventListener('click', async () => {
    const name = await showCustomInput('New Folder', 'Folder Name', '');
    if (!name) return;
    
    try {
        const res = await fetch(API_BASE + '/api/folders', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name, sub_path: currentSubPath, project_id: getEffectiveProjectId() })
        });
        const data = await res.json();
        if (data.status === 'ok') {
            loadWorkspaceFiles(); // Refresh
        } else {
            alert(data.message || 'Failed to create folder');
        }
    } catch (e) {
        console.error('New Folder error:', e);
    }
});

// ─── Claude-like View Management ──────────────────────────────────────────

function normalizeText(value) {
    return String(value || '').toLowerCase();
}

function getEffectiveProjectId() {
    return activeProjectId || 'default';
}

function getChatProjectId() {
    return chatProjectIdForThread || getEffectiveProjectId();
}

function isUntitledName(name) {
    const value = String(name || '').trim().toLowerCase();
    return !value || value === 'untitled' || value === 'untitled chat' || value === 'new chat';
}

function deriveChatTitle(text) {
    const cleaned = String(text || '')
        .replace(/\s+/g, ' ')
        .trim();
    if (!cleaned) return 'Untitled';
    const words = cleaned.split(' ').slice(0, 7).join(' ');
    return words.length > 52 ? `${words.slice(0, 49)}...` : words;
}

function setWorkspaceVisibility() {
    const shell = document.getElementById('appShell');
    const workspace = document.getElementById('workspacePanel');
    if (!shell || !workspace) return;

    const narrow = window.innerWidth < 1200;
    const showWorkspace = hasSelectedProject && currentView === 'chat' && !narrow;
    shell.classList.toggle('workspace-hidden', !showWorkspace);
    workspace.classList.toggle('hidden', !showWorkspace);
    workspace.classList.toggle('xl:flex', showWorkspace);
}

function renderProjectInspector(project) {
    const titleEl = document.getElementById('projectInspectorTitle');
    const instructionsEl = document.getElementById('projectInspectorInstructions');
    const usageEl = document.getElementById('projectInspectorUsage');
    const usageBarEl = document.getElementById('projectInspectorUsageBar');
    const metaEl = document.getElementById('projectInspectorMeta');
    const statusEl = document.getElementById('projectInspectorStatus');
    if (!titleEl || !instructionsEl || !usageEl || !usageBarEl || !metaEl || !statusEl) return;

    if (!project) {
        titleEl.textContent = 'No project selected';
        instructionsEl.textContent = 'Select a project to open workspace files and keep chats organized.';
        usageEl.textContent = '0%';
        usageBarEl.style.width = '0%';
        metaEl.textContent = '0 chats • 0 files';
        statusEl.textContent = 'Pick a project to enter workspace mode.';
        return;
    }

    const fileCount = Array.isArray(project.files) ? project.files.length : 0;
    const chatCount = Array.isArray(project.chats) ? project.chats.length : 0;
    const usagePercent = Math.min(100, fileCount * 8);
    titleEl.textContent = project.name || 'Project';
    instructionsEl.textContent = project.instructions || 'No project instructions yet.';
    usageEl.textContent = `${usagePercent}%`;
    usageBarEl.style.width = `${usagePercent}%`;
    metaEl.textContent = `${chatCount} chats • ${fileCount} files`;
    statusEl.textContent = hasSelectedProject
        ? 'Workspace unlocked. You can upload files and start chatting.'
        : 'Select this project to unlock its workspace.';
}

function renderWelcomeRecents() {
    const listEl = document.getElementById('welcomeRecentList');
    const openAllBtn = document.getElementById('welcomeOpenChatsBtn');
    if (!listEl) return;

    let candidates = [];
    if (activeProjectId) {
        const project = cachedProjects.find((p) => p.id === activeProjectId);
        candidates = (project?.chats || []).map((chat) => ({
            ...chat,
            _projectName: project?.name || 'Project',
            _projectId: project?.id || '',
        }));
    } else {
        candidates = cachedProjects.flatMap((project) =>
            (project?.chats || []).map((chat) => ({
                ...chat,
                _projectName: project?.name || 'Project',
                _projectId: project?.id || '',
            }))
        );
    }

    const sorted = [...candidates]
        .sort((a, b) => (b.created_at || 0) - (a.created_at || 0))
        .slice(0, 5);

    if (sorted.length === 0) {
        const emptyMessage = activeProjectId
            ? 'No chats yet. Start a conversation to see recents here.'
            : 'Select a project or start chatting to populate recents.';
        listEl.innerHTML = `<p class="text-xs text-gray-400 italic">${emptyMessage}</p>`;
        if (openAllBtn) openAllBtn.classList.add('opacity-40', 'pointer-events-none');
        return;
    }
    if (openAllBtn) openAllBtn.classList.remove('opacity-40', 'pointer-events-none');

    listEl.innerHTML = '';
    sorted.forEach((chat) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'welcome-recent-item w-full text-left px-3 py-2 rounded-xl';
        btn.innerHTML = `
            <div class="flex items-center justify-between gap-2">
                <span class="text-sm font-medium text-textdark truncate">${DOMPurify.sanitize(chat.name || 'Untitled')}</span>
                <span class="text-[10px] text-gray-400 whitespace-nowrap">${chat.created_at ? new Date(chat.created_at * 1000).toLocaleDateString() : ''}</span>
            </div>
            <div class="mt-1 text-[11px] text-gray-500 truncate">${DOMPurify.sanitize(chat._projectName || 'Project')}</div>
        `;
        btn.addEventListener('click', async () => {
            if (chat._projectId && chat._projectId !== activeProjectId) {
                await switchProject(chat._projectId, false);
            }
            await switchChat(chat.id);
            switchView('chat');
        });
        listEl.appendChild(btn);
    });
}

function setCustomizeTab(tabName) {
    customizeTab = tabName;
    const skillsBtn = document.getElementById('customizeSkillsTabBtn');
    const connectorsBtn = document.getElementById('customizeConnectorsTabBtn');
    const skillsPanel = document.getElementById('customizeSkillsPanel');
    const connectorsPanel = document.getElementById('customizeConnectorsPanel');

    if (skillsBtn && connectorsBtn) {
        if (tabName === 'connectors') {
            connectorsBtn.className = 'w-full text-left px-3 py-1.5 rounded-lg bg-white border border-anthropic/20 font-medium text-sm';
            skillsBtn.className = 'w-full text-left px-3 py-1.5 rounded-lg text-gray-600 hover:bg-gray-50 text-sm';
        } else {
            skillsBtn.className = 'w-full text-left px-3 py-1.5 rounded-lg bg-white border border-anthropic/20 font-medium text-sm';
            connectorsBtn.className = 'w-full text-left px-3 py-1.5 rounded-lg text-gray-600 hover:bg-gray-50 text-sm';
        }
    }

    if (skillsPanel && connectorsPanel) {
        if (tabName === 'connectors') {
            skillsPanel.classList.add('hidden');
            connectorsPanel.classList.remove('hidden');
            loadConnectorsList();
        } else {
            connectorsPanel.classList.add('hidden');
            skillsPanel.classList.remove('hidden');
            loadSkillsList();
        }
    }
}

function applyProjectsFilter() {
    const container = document.getElementById('projectsGridContainer');
    if (!container) return;
    const q = normalizeText(document.getElementById('projectsSearchInput')?.value);
    const filtered = cachedProjects.filter(p => {
        return normalizeText(p.name).includes(q) || normalizeText(p.instructions).includes(q);
    });

    container.innerHTML = '';
    if (filtered.length === 0) {
        container.innerHTML = '<p class="text-xs text-gray-400">No projects match your search.</p>';
        return;
    }

    filtered.forEach(p => {
        const card = document.createElement('div');
        const isActive = p.id === activeProjectId && hasSelectedProject;
        card.className = `p-4 bg-cloud border border-bordercolor rounded-xl hover:shadow-md transition-shadow cursor-pointer flex flex-col gap-1 ${isActive ? 'project-card-active' : ''}`;
        card.onclick = () => {
            switchProject(p.id);
            switchView('chat');
        };
        card.onmouseenter = () => renderProjectInspector(p);
        card.onmouseleave = () => renderProjectInspector(cachedProjects.find((project) => project.id === activeProjectId) || null);
        card.innerHTML = `
            <h3 class="font-semibold text-sm text-textdark">${DOMPurify.sanitize(p.name)}</h3>
            <p class="text-xs text-gray-500">${DOMPurify.sanitize(p.instructions || 'No description')}</p>
            <div class="mt-2 flex items-center justify-between text-[10px] text-gray-400 border-t pt-2 border-bordercolor">
                <span>${p.chats ? p.chats.length : 0} chats</span>
                <span>${p.files ? p.files.length : 0} files</span>
            </div>
        `;
        container.appendChild(card);
    });
}

function applyArtifactsFilter() {
    const container = document.getElementById('artifactsGridContainer');
    if (!container) return;

    const filtered = cachedArtifacts.filter((a) => {
        if (activeArtifactTab === 'mine' && !a.is_mine) return false;
        if (activeArtifactTab === 'inspiration' && a.is_mine) return false;
        const category = normalizeText(a.category);
        if (activeArtifactFilter === 'learn') return category.includes('learn');
        if (activeArtifactFilter === 'life') return category.includes('life');
        return true;
    });

    container.innerHTML = '';
    if (filtered.length === 0) {
        container.innerHTML = '<p class="text-xs text-gray-400">No artifacts found for this filter.</p>';
        return;
    }

    filtered.forEach(a => {
        const card = document.createElement('div');
        card.className = 'border border-bordercolor rounded-xl overflow-hidden hover:shadow-md transition-shadow cursor-pointer bg-white';
        card.innerHTML = `
            <img src="${a.image_url}" class="w-full h-32 object-cover bg-gray-50" alt="${a.name}">
            <div class="p-3 space-y-1">
                <span class="text-[10px] bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded-full">${a.category}</span>
                <h4 class="font-medium text-sm text-textdark truncate">${a.name}</h4>
                <p class="text-xs text-gray-500 line-clamp-2">${a.description}</p>
            </div>
        `;
        container.appendChild(card);
    });
}

function applyChatsFilter() {
    const container = document.getElementById('chatsListContainer');
    if (!container) return;
    const q = normalizeText(document.getElementById('chatsSearchInput')?.value);
    const sorted = [...cachedChats].sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
    const filtered = sorted.filter(chat => normalizeText(chat.name || 'Untitled Chat').includes(q));

    container.innerHTML = '';
    if (filtered.length === 0) {
        container.innerHTML = '<p class="text-xs text-gray-400 italic">No chats match your search</p>';
        return;
    }

    filtered.forEach(chat => {
        const item = document.createElement('div');
        item.className = 'p-3 bg-white border border-bordercolor rounded-xl hover:shadow-sm transition-shadow cursor-pointer flex items-center justify-between';
        item.onclick = () => {
            switchChat(chat.id);
            switchView('chat');
        };
        item.innerHTML = `
            <div class="flex items-center gap-3">
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="text-gray-400"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                <span class="text-sm font-medium text-textdark truncate">${chat.name || 'Untitled Chat'}</span>
            </div>
            <span class="text-[11px] text-gray-400">${new Date(chat.created_at * 1000).toLocaleDateString()}</span>
        `;
        container.appendChild(item);
    });
}

function spotlightApplySelectionHighlight() {
    document.querySelectorAll('.spotlight-result').forEach((el, i) => {
        el.classList.toggle('spotlight-result-active', i === spotlightSelectedIndex);
    });
}

async function spotlightActivateItem(item) {
    if (!item) return;
    if (item.type === 'chat') {
        await switchChat(item.id);
        switchView('chat');
    } else {
        await switchProject(item.id);
        switchView('chat');
    }
    closeSearchModal();
}

function renderSpotlightResults(query) {
    const container = document.getElementById('spotlightResults');
    if (!container) return;

    const q = normalizeText(query);
    const projectMatches = cachedProjects.filter(p =>
        normalizeText(p.name).includes(q) || normalizeText(p.instructions).includes(q)
    );
    const chatMatches = cachedChats.filter(c =>
        normalizeText(c.name || 'Untitled Chat').includes(q)
    );

    const maxEach = q ? 40 : 20;
    const projects = projectMatches.slice(0, maxEach).map(p => ({
        type: 'project',
        id: p.id,
        title: p.name,
        subtitle: p.instructions ? String(p.instructions).slice(0, 80) : 'Project'
    }));
    const chats = chatMatches.slice(0, maxEach).map(c => ({
        type: 'chat',
        id: c.id,
        title: c.name || 'Untitled',
        subtitle: 'Chat'
    }));

    spotlightResultsFlat = [...projects, ...chats];
    spotlightSelectedIndex = spotlightResultsFlat.length ? 0 : -1;

    if (!spotlightResultsFlat.length) {
        container.innerHTML = `<p class="px-4 py-6 text-xs text-center text-gray-500">${q ? 'No matches.' : 'No chats or projects yet.'}</p>`;
        return;
    }

    container.innerHTML = '';
    spotlightResultsFlat.forEach((item, index) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = `spotlight-result ${index === 0 ? 'spotlight-result-active' : ''}`;
        btn.dataset.spotlightIndex = String(index);
        const kind = item.type === 'project' ? 'Project' : 'Chat';
        btn.innerHTML = `
            <span class="text-[10px] uppercase tracking-wider text-gray-500 w-14 shrink-0">${kind}</span>
            <span class="flex-1 min-w-0">
                <span class="block font-medium truncate">${item.title}</span>
                ${item.subtitle && item.subtitle !== 'Chat' ? `<span class="block text-[11px] text-gray-500 truncate">${item.subtitle}</span>` : ''}
            </span>
        `;
        btn.addEventListener('click', () => spotlightActivateItem(item));
        container.appendChild(btn);
    });
}

function closeSearchModal() {
    const modal = document.getElementById('searchModal');
    if (!modal) return;
    modal.classList.add('hidden');
}

async function openSearchModal() {
    const modal = document.getElementById('searchModal');
    const input = document.getElementById('popupSearchInput');
    if (!modal || !input) return;
    modal.classList.remove('hidden');
    const results = document.getElementById('spotlightResults');
    if (results) results.innerHTML = '<p class="px-4 py-3 text-xs text-gray-500">Loading…</p>';
    input.value = '';
    const loaded = await loadSearchViewData();
    if (loaded) renderSpotlightResults('');
    setTimeout(() => input.focus(), 20);
}

function switchView(viewName) {
    currentView = viewName;
    
    // Hide all views (support both old .view-pane and new .view classes)
    document.querySelectorAll('.view-pane, .view').forEach(p => {
        p.classList.add('hidden');
        p.classList.remove('active');
    });
    
    // Show target view
    const target = document.getElementById(`view-${viewName}`);
    if (target) {
        target.classList.remove('hidden');
        target.classList.add('active');
        if (viewName === 'customize') target.classList.add('flex');
    }
    
    // Update nav active state
    document.querySelectorAll('.nav-item').forEach(item => {
        const itemView = item.getAttribute('data-view');
        if (itemView === viewName) {
            item.classList.add('bg-gray-100', 'font-medium', 'active');
        } else {
            item.classList.remove('bg-gray-100', 'font-medium', 'active');
        }
    });

    // Load data conditionally
    if (viewName === 'projects') loadProjectsGrid();
    if (viewName === 'artifacts') loadArtifactsGrid();
    if (viewName === 'customize') setCustomizeTab(customizeTab);
    if (viewName === 'chats') loadChatsList();
    if (viewName === 'welcome') renderWelcomeRecents();

    document.querySelectorAll('.mobile-nav-btn').forEach((btn) => {
        const isActive = btn.getAttribute('data-mobile-view') === viewName;
        btn.classList.toggle('bg-anthropic/20', isActive);
        btn.classList.toggle('text-anthropic', isActive);
    });
    setWorkspaceVisibility();
    if (viewName === 'welcome' || viewName === 'chat') {
        renderPreviews(); // Keep attachment chips in sync across views
    }
}

function initNavigation() {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            const view = item.getAttribute('data-view');
            if (view === 'search') {
                openSearchModal();
                return;
            }
            if (view) switchView(view);
        });
    });

    // Welcome Input Handler
    const welcomeInput = document.getElementById('welcomeInput');
    const welcomeSendBtn = document.getElementById('welcomeSendBtn');
    
    if (welcomeInput && welcomeSendBtn) {
        welcomeSendBtn.addEventListener('click', () => {
            const text = welcomeInput.value.trim();
            if (!text && pendingFiles.length === 0) return;
            
            // Switch to Chat View
            switchView('chat');
            
            // Transfer text to main chat design
            messageInput.value = text;
            welcomeInput.value = ''; // clear
            
            // Trigger Submit
            chatForm.dispatchEvent(new Event('submit'));
        });

        welcomeInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                welcomeSendBtn.click();
            }
        });
    }

    document.getElementById('welcomeAttachBtn')?.addEventListener('click', (e) => {
        e.stopPropagation();
        const btn = document.getElementById('welcomeAttachBtn');
        if (btn) toggleComposerPlusMenu(btn);
    });
    document.getElementById('welcomeStyleBtn')?.addEventListener('click', (e) => {
        e.stopPropagation();
        const btn = document.getElementById('welcomeStyleBtn');
        if (btn) toggleStyleSubmenuOnly(btn);
    });

    document.getElementById('connectToolsBar')?.addEventListener('click', () => {
        switchView('customize');
        setCustomizeTab('connectors');
    });

    document.getElementById('welcomeOpenChatsBtn')?.addEventListener('click', () => {
        switchView('chats');
    });

    document.querySelectorAll('.mobile-nav-btn').forEach((btn) => {
        btn.addEventListener('click', () => {
            const view = btn.getAttribute('data-mobile-view');
            if (view) switchView(view);
        });
    });

    document.getElementById('projectsSearchInput')?.addEventListener('input', applyProjectsFilter);
    document.getElementById('chatsSearchInput')?.addEventListener('input', applyChatsFilter);
    document.getElementById('popupSearchInput')?.addEventListener('input', (e) => renderSpotlightResults(e.target.value));
    document.getElementById('popupSearchInput')?.addEventListener('keydown', (e) => {
        const modal = document.getElementById('searchModal');
        if (!modal || modal.classList.contains('hidden')) return;
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            if (spotlightResultsFlat.length) {
                spotlightSelectedIndex = Math.min(spotlightSelectedIndex + 1, spotlightResultsFlat.length - 1);
                spotlightApplySelectionHighlight();
            }
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            if (spotlightResultsFlat.length) {
                spotlightSelectedIndex = Math.max(spotlightSelectedIndex - 1, 0);
                spotlightApplySelectionHighlight();
            }
        } else if (e.key === 'Enter') {
            e.preventDefault();
            const item = spotlightResultsFlat[spotlightSelectedIndex];
            if (item) spotlightActivateItem(item);
        }
    });
    document.getElementById('searchModal')?.addEventListener('click', (e) => {
        if (e.target === document.getElementById('searchModal')) closeSearchModal();
    });

    document.querySelectorAll('.artifact-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            activeArtifactTab = btn.dataset.artifactTab || 'inspiration';
            document.querySelectorAll('.artifact-tab').forEach(tab => {
                tab.className = 'artifact-tab pb-2 text-gray-500 hover:text-gray-700';
            });
            btn.className = 'artifact-tab pb-2 border-b-2 border-anthropic font-medium text-gray-800';
            applyArtifactsFilter();
        });
    });

    document.querySelectorAll('.artifact-filter').forEach(btn => {
        btn.addEventListener('click', () => {
            activeArtifactFilter = btn.dataset.artifactFilter || 'all';
            document.querySelectorAll('.artifact-filter').forEach(filterBtn => {
                filterBtn.className = 'artifact-filter px-3 py-1.5 bg-gray-50 hover:bg-gray-100 text-gray-600 rounded-full border border-gray-100';
            });
            btn.className = 'artifact-filter px-3 py-1.5 bg-black text-white rounded-full';
            applyArtifactsFilter();
        });
    });

    document.getElementById('customizeSkillsTabBtn')?.addEventListener('click', () => setCustomizeTab('skills'));
    document.getElementById('customizeConnectorsTabBtn')?.addEventListener('click', () => setCustomizeTab('connectors'));
}

async function loadProjectsGrid() {
    const container = document.getElementById('projectsGridContainer');
    if (!container) return;
    container.innerHTML = '<p class="text-xs text-gray-400">Loading projects...</p>';
    
    try {
        const res = await fetch(API_BASE + '/api/projects');
        cachedProjects = await res.json();
        applyProjectsFilter();
        renderProjectInspector(cachedProjects.find((p) => p.id === activeProjectId) || null);
    } catch (e) {
        container.innerHTML = '<p class="text-xs text-red-500">Failed to load projects</p>';
    }
}

async function loadArtifactsGrid() {
    const container = document.getElementById('artifactsGridContainer');
    if (!container) return;
    container.innerHTML = '<p class="text-xs text-gray-400">Loading artifacts...</p>';
    
    try {
        const res = await fetch(API_BASE + '/api/artifacts');
        cachedArtifacts = await res.json();
        applyArtifactsFilter();
    } catch (e) {
        container.innerHTML = '<p class="text-xs text-red-500">Failed to load artifacts</p>';
    }
}

async function loadSkillsList() {
    const container = document.getElementById('skillsListContainer');
    if (!container) return;
    container.innerHTML = '<p class="text-xs text-gray-400">Loading skills...</p>';
    
    try {
        const res = await fetch(API_BASE + '/api/tools');
        cachedTools = await res.json();
        container.innerHTML = '';
        cachedTools.forEach(t => {
            const item = document.createElement('div');
            item.className = 'p-3 border border-bordercolor rounded-xl flex items-start justify-between hover:bg-cloud/50 transition-colors bg-white';
            item.innerHTML = `
                <div class="flex items-start gap-3">
                    <div class="p-2 bg-gray-100 rounded-lg text-gray-600">
                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
                    </div>
                    <div>
                        <h4 class="font-medium text-sm text-textdark font-mono">${t.name}</h4>
                        <p class="text-xs text-gray-500 mt-0.5">${t.description}</p>
                    </div>
                </div>
                <div class="flex items-center gap-2">
                     <span class="text-[10px] bg-green-50 text-green-700 border border-green-200 px-1.5 py-0.5 rounded">Active</span>
                </div>
            `;
            container.appendChild(item);
        });
    } catch (e) {
        container.innerHTML = '<p class="text-xs text-red-500">Failed to load skills</p>';
    }
}

function loadConnectorsList() {
    const container = document.getElementById('connectorsListContainer');
    if (!container) return;
    container.innerHTML = '';

    if (!cachedTools.length) {
        container.innerHTML = '<p class="text-xs text-gray-400">No connectors available.</p>';
        return;
    }

    cachedTools.forEach((tool) => {
        const item = document.createElement('div');
        const requiresAuth = Boolean(tool?.auth_required || tool?.requires_auth || tool?.name === 'mcp_auth');
        item.className = 'p-3 border border-bordercolor rounded-xl bg-white flex items-center justify-between';
        item.innerHTML = `
            <div>
                <p class="text-sm font-medium text-textdark">${tool.name}</p>
                <p class="text-xs text-gray-500">${tool.description || 'Connector integration'}</p>
            </div>
            <span class="text-[10px] px-2 py-1 rounded-full ${requiresAuth ? 'bg-yellow-50 text-yellow-700 border border-yellow-300' : 'bg-green-50 text-green-700 border border-green-300'}">
                ${requiresAuth ? 'Needs setup' : 'Ready'}
            </span>
        `;
        container.appendChild(item);
    });
}

async function loadChatsList() {
    const container = document.getElementById('chatsListContainer');
    if (!container) return;
    container.innerHTML = '<p class="text-xs text-gray-400">Loading chats...</p>';
    
    try {
        const res = await fetch(`${API_BASE}/api/projects/${getEffectiveProjectId()}`);
        const project = await res.json();
        container.innerHTML = '';
        cachedChats = (project.chats || []).sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
        if (cachedChats.length === 0) {
            container.innerHTML = '<p class="text-xs text-gray-400 italic">No chats in this project</p>';
            return;
        }
        applyChatsFilter();
    } catch (e) {
        container.innerHTML = '<p class="text-xs text-red-500">Failed to load chats</p>';
    }
}

async function loadSearchViewData() {
    try {
        const [projectsRes, projectRes] = await Promise.all([
            fetch(API_BASE + '/api/projects'),
            fetch(`${API_BASE}/api/projects/${getEffectiveProjectId()}`)
        ]);
        cachedProjects = await projectsRes.json();
        const activeProject = await projectRes.json();
        cachedChats = activeProject.chats || [];
        return true;
    } catch (e) {
        const el = document.getElementById('spotlightResults');
        if (el) el.innerHTML = '<p class="px-4 py-6 text-xs text-center text-red-400">Could not load search. Check the API is running.</p>';
        return false;
    }
}

function focusPrimaryInput() {
    const activeInput = currentView === 'welcome'
        ? document.getElementById('welcomeInput')
        : messageInput;

    if (!activeInput) return;
    activeInput.focus();
    const len = activeInput.value?.length || 0;
    if (typeof activeInput.setSelectionRange === 'function') {
        activeInput.setSelectionRange(len, len);
    }
}

// Keyboard QoL shortcuts:
// - Cmd/Ctrl+K: focus current prompt input
// - Cmd/Ctrl+Enter: send from active view input
document.addEventListener('keydown', (e) => {
    const isMeta = e.metaKey || e.ctrlKey;
    if (!isMeta) return;
    const settingsOpen = settingsModal && !settingsModal.classList.contains('hidden');
    if (settingsOpen) return;

    if (e.key.toLowerCase() === 'k') {
        e.preventDefault();
        focusPrimaryInput();
        return;
    }

    if (e.key === 'Enter') {
        e.preventDefault();
        if (currentView === 'welcome') {
            document.getElementById('welcomeSendBtn')?.click();
        } else {
            chatForm?.dispatchEvent(new Event('submit'));
        }
    }
});

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeSearchModal();
        closeComposerPlusMenu();
    }
});

window.addEventListener('resize', () => {
    closeComposerPlusMenu();
    setWorkspaceVisibility();
});

// Trigger initializations
if (typeof switchView === 'function') switchView('welcome');
if (typeof initNavigation === 'function') initNavigation();
renderWelcomeRecents();

// ─── Mobile Sidebar ────────────────────────────────────────────────────────

function toggleMobileSidebar(open) {
    const sidebar = document.getElementById('sidebar') || document.getElementById('sidebarEl');
    const overlay = document.getElementById('sidebarOverlay');
    if (!sidebar) return;
    if (open) {
        sidebar.classList.add('open', 'sidebar-open');
        sidebar.classList.remove('hidden');
        sidebar.classList.add('flex');
        if (overlay) overlay.classList.add('active');
    } else {
        sidebar.classList.remove('open', 'sidebar-open');
        if (overlay) overlay.classList.remove('active');
        if (window.innerWidth < 768) {
            setTimeout(() => {
                if (!sidebar.classList.contains('open') && !sidebar.classList.contains('sidebar-open')) {
                    sidebar.classList.add('hidden');
                    sidebar.classList.remove('flex');
                }
            }, 220);
        }
    }
}

// Close sidebar on nav click (mobile)
document.querySelectorAll('#mainNav .nav-item, #newChatBtn').forEach((btn) => {
    btn.addEventListener('click', () => {
        if (window.innerWidth < 768) toggleMobileSidebar(false);
    });
});

// ─── Utilities ─────────────────────────────────────────────────────────────

if (typeof escapeHtml !== 'function') {
    window.escapeHtml = function(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    };
}

// ─── Global API (used by HTML onclick handlers) ────────────────────────────

window.toggleMobileSidebar = toggleMobileSidebar;
window.submitAskUserResponse = submitAskUserResponse;
window.submitAskUserChoice = submitAskUserChoice;

window.App = {
    toggleSidebar: toggleMobileSidebar,
    openSettings() {
        const modal = document.getElementById('settingsModal');
        if (modal) { modal.classList.remove('hidden'); modal.classList.add('flex'); }
        if (typeof loadSettingsData === 'function') loadSettingsData();
    },
    closeSettings() {
        const modal = document.getElementById('settingsModal');
        if (modal) { modal.classList.add('hidden'); modal.classList.remove('flex'); }
    },
    closeFileViewer() {
        const modal = document.getElementById('fileViewerModal');
        if (modal) { modal.classList.add('hidden'); modal.classList.remove('flex'); }
    },
    closeSearch() {
        const modal = document.getElementById('searchModal');
        if (modal) { modal.classList.add('hidden'); modal.classList.remove('flex'); }
    },
};
