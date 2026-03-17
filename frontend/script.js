// State management
let currentSessionId = generateUUID();
let socket = null;
let isReasoning = false;
let pendingFiles = []; // { name, type, data (base64), preview? }
let activeMode = 'tools_on'; // default: 'tools_on' or 'tools_off'
let activeProjectId = 'default';
let activeAiMessage = null; 
let lastHumanMessage = ""; // For regenerate

// DOM Elements
const chatContainer = document.getElementById('chatContainer');
const messagesArea = document.getElementById('messagesArea');
const chatForm = document.getElementById('chatForm');
const messageInput = document.getElementById('messageInput');
const sendBtn = document.getElementById('sendBtn');
const sessionIdEl = document.getElementById('sessionId');
const newChatBtn = document.getElementById('newChatBtn');
const statusDot = document.getElementById('connectionStatusDot');
const statusText = document.getElementById('connectionStatusText');
const mobileDot = document.getElementById('mobileConnectionDot');
const agentStatus = document.getElementById('agentStatus');
const dragOverlay = document.getElementById('dragOverlay');
const attachmentPreviews = document.getElementById('attachmentPreviews');
const fileInput = document.getElementById('fileInput');
const attachBtn = document.getElementById('attachBtn');
const modeFastBtn = document.getElementById('modeFastBtn');
const modeReasoningBtn = document.getElementById('modeReasoningBtn');
const projectsListEl = document.getElementById('projectsList');
const addProjectBtn = document.getElementById('addProjectBtn');
const projectKnowledgeSection = document.getElementById('projectKnowledgeSection');
const projectFilesList = document.getElementById('projectFilesList');
const projectChatsSection = document.getElementById('projectChatsSection');
const projectChatsList = document.getElementById('projectChatsList');

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
sessionIdEl.value = currentSessionId;
connectWebSocket();
loadSettingsData();
loadProjects();

async function loadSettingsData() {
    try {
        const [profileRes, personaRes, memoriesRes] = await Promise.all([
            fetch('/api/profile'),
            fetch('/api/persona'),
            fetch('/api/memories')
        ]);
        
        const profile = await profileRes.json();
        const persona = await personaRes.json();
        const memories = await memoriesRes.json();

        // Populate Profile
        if (profileNameInput) profileNameInput.value = profile.name || '';
        if (profileLangInput) profileLangInput.value = profile.preferred_language || 'en';
        if (profileStyleInput) profileStyleInput.value = profile.response_style || 'detailed';
        if (profileLlmUrlInput) profileLlmUrlInput.value = profile.llm_base_url || 'http://127.0.0.1:8080/v1';
        if (profileLlmModelInput) profileLlmModelInput.value = profile.llm_model_name || 'mlx-community/Qwen2-VL-7B-Instruct-4bit';

        // Populate Persona
        if (personaNameInput) personaNameInput.value = persona.name || '';
        if (personaToneInput) personaToneInput.value = persona.tone || '';
        if (agentNameDisplay) agentNameDisplay.innerHTML = `
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-anthropic"><path d="M12 2a8 8 0 0 0-8 8c0 5.4 7.05 11.5 7.35 11.76a1 1 0 0 0 1.3 0C12.95 21.5 20 15.4 20 10a8 8 0 0 0-8-8z"/><circle cx="12" cy="10" r="3"/></svg>
            ${persona.name || 'Owlynn'}
        `;
        if (agentRoleDisplay) agentRoleDisplay.innerText = persona.role || '';

        // Populate Memories
        if (memoriesCountEl) memoriesCountEl.innerText = memories.length || 0;
        renderMemories(memories);

    } catch (e) {
        console.error('Failed to load settings data:', e);
    }
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
    if (!confirm(`Forget this memory: "${fact}"?`)) return;
    
    try {
        const res = await fetch('/api/memories', {
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

addMemoryBtn?.addEventListener('click', async () => {
    const fact = newMemoryInput.value.trim();
    if (!fact) return;
    
    try {
        const res = await fetch('/api/memories', {
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
        const res = await fetch('/api/projects');
        const projects = await res.json();
        renderProjects(projects);
        
        // Load active project details
        const activeProject = projects.find(p => p.id === activeProjectId) || projects[0];
        if (activeProject) {
            switchProject(activeProject.id, false);
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
            <span class="truncate ${isActive ? 'font-medium text-textdark' : ''}">${project.name}</span>
        `;
        
        item.onclick = () => switchProject(project.id);
        projectsListEl.appendChild(item);
    });
}

async function switchProject(projectId, resetChat = true) {
    activeProjectId = projectId;
    
    try {
        const res = await fetch(`/api/projects/${projectId}`);
        const project = await res.json();
        
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
        const allRes = await fetch('/api/projects');
        const allProjects = await allRes.json();
        renderProjects(allProjects);
        
        if (resetChat) {
            // Reset reasoning state
            updateAgentStatus('idle');
            
            // Load project-specific session ID
            const savedSessionId = localStorage.getItem(`project_session_${projectId}`);
            if (savedSessionId) {
                currentSessionId = savedSessionId;
                sessionIdEl.value = currentSessionId;
                await loadChatHistory(currentSessionId);
                
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
    
    try {
        const res = await fetch(`/api/history/${sessionId}`);
        const history = await res.json();
        
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
        const item = document.createElement('div');
        item.className = `flex items-center gap-2 p-2 rounded text-xs cursor-pointer transition-colors ${
            isActive ? 'bg-anthropic text-white' : 'bg-white border border-bordercolor hover:bg-gray-50'
        }`;
        
        const date = chat.created_at ? new Date(chat.created_at * 1000).toLocaleDateString() : 'Unknown';
        
        item.innerHTML = `
            <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${isActive ? 3 : 2}" stroke-linecap="round" stroke-linejoin="round" class="${isActive ? 'text-white' : 'text-gray-400'}"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
            <span class="truncate flex-1 font-medium">${chat.name || 'Chat'}</span>
            <span class="opacity-60 text-[10px]">${date}</span>
        `;
        
        item.onclick = () => switchChat(chat.id);
        projectChatsList.appendChild(item);
    });
}

async function switchChat(sessionId) {
    currentSessionId = sessionId;
    sessionIdEl.value = currentSessionId;
    
    // Update mapping in localStorage
    if (activeProjectId) {
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
    const res = await fetch(`/api/projects/${activeProjectId}`);
    const project = await res.json();
    renderProjectChats(project.chats || []);
}

addProjectBtn?.addEventListener('click', async () => {
    const name = prompt('Project Name:');
    if (!name) return;
    
    const instructions = prompt('Project Instructions (optional):');
    
    try {
        const res = await fetch('/api/projects', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, instructions })
        });
        const newProject = await res.json();
        await loadProjects();
        switchProject(newProject.id);
    } catch (e) {
        console.error('Failed to create project:', e);
    }
});

// ─── Event Listeners ────────────────────────────────────────────────────────

openSettingsBtn?.addEventListener('click', () => {
    settingsModal.classList.remove('hidden');
    loadSettingsData();
});

closeSettingsBtn?.addEventListener('click', () => settingsModal.classList.add('hidden'));
closeSettingsFooterBtn?.addEventListener('click', () => settingsModal.classList.add('hidden'));

// Close modal when clicking outside content
settingsModal?.addEventListener('click', (e) => {
    if (e.target === settingsModal) {
        settingsModal.classList.add('hidden');
    }
});

saveProfileBtn?.addEventListener('click', async () => {
    const data = {
        name: profileNameInput.value,
        preferred_language: profileLangInput.value,
        response_style: profileStyleInput.value,
        llm_base_url: profileLlmUrlInput.value,
        llm_model_name: profileLlmModelInput.value
    };
    try {
        await fetch('/api/profile', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
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
        const res = await fetch('/api/persona', {
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
    
    currentSessionId = generateUUID();
    sessionIdEl.value = currentSessionId;
    messagesArea.innerHTML = '';
    pendingFiles = [];
    renderPreviews();
    
    const chatName = prompt('Enter a name for this chat (optional):', 'New Chat') || 'New Chat';
    
    // Save mapping to localStorage
    if (activeProjectId) {
        localStorage.setItem(`project_session_${activeProjectId}`, currentSessionId);
        
        // Register chat with project in backend
        try {
            await fetch(`/api/projects/${activeProjectId}/chats`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: currentSessionId, name: chatName })
            });
            
            // Refresh project details to show new chat in list
            const res = await fetch(`/api/projects/${activeProjectId}`);
            const project = await res.json();
            if (projectChatsSection) projectChatsSection.classList.remove('hidden');
            renderProjectChats(project.chats || []);
        } catch (e) {
            console.error('Failed to register chat with project:', e);
        }
    }
    
    if (socket) {
        socket.onclose = null; // Prevent auto-reconnect
        socket.close();
    }
    connectWebSocket();
    
    // Welcome message
    renderMessage({ type: 'ai', content: `**${chatName}** started. How can I help you in the workspace today?` });
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
    if (activeMode === 'tools_off') {
        modeFastBtn.className = 'px-3 py-1 font-medium bg-anthropic text-white transition-colors';
        modeReasoningBtn.className = 'px-3 py-1 font-medium text-gray-500 hover:bg-gray-50 transition-colors';
    } else {
        modeFastBtn.className = 'px-3 py-1 font-medium text-gray-500 hover:bg-gray-50 transition-colors';
        modeReasoningBtn.className = 'px-3 py-1 font-medium bg-anthropic text-white transition-colors';
    }
}

// Paperclip button opens file picker
attachBtn.addEventListener('click', () => fileInput.click());

fileInput.addEventListener('change', (e) => processFiles(e.target.files));

// ─── Drag and Drop ──────────────────────────────────────────────────────────
document.body.addEventListener('dragenter', (e) => {
    e.preventDefault();
    if (e.dataTransfer.types.includes('Files')) {
        dragOverlay.classList.remove('hidden');
    }
});

document.body.addEventListener('dragover', (e) => {
    e.preventDefault();
});

document.body.addEventListener('dragleave', (e) => {
    // Only hide when leaving the body entirely
    if (!e.relatedTarget || e.relatedTarget === document.body) {
        dragOverlay.classList.add('hidden');
    }
});

document.body.addEventListener('drop', (e) => {
    e.preventDefault();
    dragOverlay.classList.add('hidden');
    processFiles(e.dataTransfer.files);
});

// WebSocket Logic
function connectWebSocket() {
    updateConnectionStatus('connecting');
    
    socket = new WebSocket(`ws://127.0.0.1:8000/ws/chat/${currentSessionId}`);
    
    socket.onopen = () => {
        updateConnectionStatus('connected');
    };
    
    socket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        
        if (data.type === 'status') {
            updateAgentStatus(data.content);
        } else if (data.type === 'message') {
            renderMessage(data.message);
        } else if (data.type === 'chunk') {
            handleChunk(data.content);
        } else if (data.type === 'error') {
            renderError(data.content);
            updateAgentStatus('idle');
        }
    };
    
    socket.onclose = () => {
        updateConnectionStatus('disconnected');
        // Auto reconnect after 3 seconds
        setTimeout(connectWebSocket, 3000);
    };
    
    socket.onerror = (error) => {
        console.error('WebSocket Error:', error);
    };
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
        mobileDot.className = 'w-2 h-2 rounded-full bg-green-500';
        statusText.textContent = 'Connected to MLX API';
        sendBtn.disabled = false;
    } else if (status === 'connecting') {
        statusDot.className = 'w-2 h-2 rounded-full bg-yellow-500 hover:animate-pulse';
        mobileDot.className = 'w-2 h-2 rounded-full bg-yellow-500 hover:animate-pulse';
        statusText.textContent = 'Connecting...';
        sendBtn.disabled = true;
    } else {
        statusDot.className = 'w-2 h-2 rounded-full bg-red-500';
        mobileDot.className = 'w-2 h-2 rounded-full bg-red-500';
        statusText.textContent = 'Disconnected';
        sendBtn.disabled = true;
    }
}

function updateAgentStatus(status) {
    if (status === 'idle') {
        isReasoning = false;
        agentStatus.textContent = 'Waiting for input...';
        agentStatus.className = 'mt-2 text-xs font-mono text-gray-400';
        sendBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>';
        
        finalizeActiveMessage();
    } else {
        isReasoning = true;
        agentStatus.textContent = 'Agent is reasoning...';
        agentStatus.className = 'mt-2 text-xs font-mono text-anthropic animate-pulse';
        sendBtn.innerHTML = '<div class="w-5 h-5 border-2 border-gray-300 border-t-gray-600 rounded-full animate-spin"></div>';
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
    attachmentPreviews.innerHTML = '';
    if (pendingFiles.length === 0) {
        attachmentPreviews.classList.add('hidden');
        return;
    }
    attachmentPreviews.classList.remove('hidden');
    attachmentPreviews.className = 'flex flex-wrap gap-2 mb-2';
    
    pendingFiles.forEach((f, idx) => {
        const chip = document.createElement('div');
        chip.className = 'relative flex items-center gap-2 bg-cloud border border-bordercolor rounded-lg px-3 py-1.5 text-sm';
        
        if (f.preview) {
            const img = document.createElement('img');
            img.src = f.preview;
            img.className = 'w-8 h-8 object-cover rounded';
            chip.appendChild(img);
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
        
        attachmentPreviews.appendChild(chip);
    });
}

function handleChunk(chunkText) {
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

    activeAiMessage.buffer += chunkText;
    let buf = activeAiMessage.buffer;

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
    }
}

function addMessageActions(contentDiv, textContent, wrapper) {
    if (contentDiv.querySelector('.message-actions')) return; 

    const actionsDiv = document.createElement('div');
    actionsDiv.className = 'message-actions flex gap-2 mt-3 pt-2 border-t border-gray-100';
    
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
              socket.send(JSON.stringify({ 
                  message: lastHumanMessage, 
                  files: [], 
                  mode: activeMode 
              }));
         }
    });

    actionsDiv.appendChild(copyBtn);
    actionsDiv.appendChild(regenBtn);
    contentDiv.appendChild(actionsDiv);
}
function handleSend(e) {
    e.preventDefault();
    const text = messageInput.value.trim();
    if ((!text && pendingFiles.length === 0) || isReasoning || socket.readyState !== WebSocket.OPEN) return;
    
    // Optimistic UI
    renderUserMessage(text, pendingFiles);
    lastHumanMessage = text; // Remember for regenerate
    
    // Send to backend with files and current mode
    socket.send(JSON.stringify({ 
        message: text, 
        files: pendingFiles.map(f => ({ name: f.name, type: f.type, data: f.data })),
        mode: activeMode,
        project_id: activeProjectId
    }));

    
    // Clear
    messageInput.value = '';
    messageInput.style.height = '56px';
    pendingFiles = [];
    renderPreviews();
    fileInput.value = '';
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
        const bubble = document.createElement('div');
        bubble.className = 'bg-userbubble text-textdark px-5 py-3 rounded-2xl text-base relative group';
        
        const textSpan = document.createElement('span');
        if (typeof text === 'string') {
            textSpan.textContent = text;
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
    
    wrapper.appendChild(inner);
    messagesArea.appendChild(wrapper);
    scrollToBottom();
}

function renderMessage(msg) {
    if (msg.type === 'human') {
        renderUserMessage(msg.content);
        return;
    }

    // Guard up-front: skip messages with no useful content at all
    const hasContent = msg.content && msg.content.trim();
    const hasToolCalls = msg.tool_calls && msg.tool_calls.length > 0;
    if (msg.type === 'ai' && !hasContent && !hasToolCalls) return;
    if (msg.type === 'tool' && !msg.content) return;

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
        // Reorder: Tool calls ABOVE content if both exist
        if (hasToolCalls) {
            msg.tool_calls.forEach(tc => {
                const toolDiv = createToolCallUI(tc);
                contentContainer.appendChild(toolDiv);
            });
        }

        if (hasContent) {
            const textDiv = document.createElement('div');
            // Strip any residual ```json ... ``` fences
            const sanitized = msg.content
                .replace(/```(?:json)?\s*\{[^}]*\}\s*```/gs, '')
                .replace(/```(?:json)?\s*```/g, '')
                .trim();
            if (sanitized) {
                textDiv.innerHTML = marked.parse(sanitized);
                contentContainer.appendChild(textDiv);
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
        
        const out = msg.content;
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
    const wrapper = document.createElement('div');
    wrapper.className = 'flex justify-center my-4';
    
    const errDiv = document.createElement('div');
    errDiv.className = 'bg-red-50 text-red-600 px-4 py-2 rounded-lg text-sm border border-red-200 shadow-sm flex items-center gap-2';
    errDiv.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg> ${err}`;
    
    wrapper.appendChild(errDiv);
    messagesArea.appendChild(wrapper);
    scrollToBottom();
}

// Helpers
function generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        var r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

function scrollToBottom() {
    chatContainer.scrollTop = chatContainer.scrollHeight;
}
