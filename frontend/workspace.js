const title = document.querySelector("#workspaceTitle");
const heading = document.querySelector("#workspaceHeading");
const subtitle = document.querySelector("#workspaceSubtitle");
const cards = document.querySelector("#workspaceCards");
const tableTitle = document.querySelector("#workspaceTableTitle");
const tableHint = document.querySelector("#workspaceTableHint");
const head = document.querySelector("#workspaceHead");
const body = document.querySelector("#workspaceBody");
const search = document.querySelector("#workspaceSearch");
const tabs = document.querySelector("#workspaceTabs");
const filters = document.querySelector("#workspaceFilters");
const grid = document.querySelector("#workspaceGrid");
const primaryAction = document.querySelector("#workspacePrimaryAction");
const drawer = document.querySelector("#workspaceDrawer");
const drawerContent = document.querySelector("#workspaceDrawerContent");
const drawerClose = document.querySelector("#workspaceDrawerClose");

let rowsCache = [];
let currentTab = "all";
let viewMode = "grid";

const routes = {
  "/dashboard": {
    title: "Home",
    section: "operation",
    breadcrumb: "Operação / Home",
    external: true,
  },
  "/overview": {
    title: "Visão geral",
    section: "operation",
    breadcrumb: "Operação / Visão geral",
    external: true,
  },
  "/cameras": {
    title: "Câmeras",
    section: "operation",
    breadcrumb: "Operação / Câmeras",
    permissions: [],
    heading: "Câmeras",
    subtitle: "Pontos conectados, status e últimas atualizações.",
    endpoint: "/cameras/estado",
    action: "Adicionar câmera",
    actionHref: "/settings/cameras",
    emptyTitle: "Nenhuma câmera cadastrada.",
    emptyDescription: "Cadastre uma câmera RTSP para acompanhar a operação pela Campex.",
    tabs: ["Todas", "Ativa", "Sem sinal", "Em configuração", "Pausada"],
    filters: ["Status", "Unidade"],
    columns: ["Câmera", "Localização", "Status", "Último evento", "Última atualização", "Ações"],
    row: (camera) => [
      camera.nome || "Câmera",
      camera.unidade_id || "—",
      badge(cameraStatusLabel(camera.status)),
      camera.ultimo_erro || "Sem evento",
      camera.ultimo_frame || camera.criado_em || "—",
      rowMenu(),
    ],
    card: cameraCard,
  },
  "/events": {
    title: "Eventos",
    section: "operation",
    breadcrumb: "Operação / Eventos",
    permissions: [],
    heading: "Eventos",
    subtitle: "Tabela completa de ocorrências operacionais com filtros.",
    endpoint: "/eventos",
    action: "Exportar eventos",
    emptyTitle: "Nenhum evento registrado.",
    emptyDescription: "Os eventos aparecerão aqui quando a operação gerar histórico.",
    tabs: ["Todos", "Paradas", "Pessoas", "Máquinas", "Com evidência"],
    filters: ["Período", "Câmera", "Tipo de evento", "Status", "Área", "Evidência"],
    columns: ["Evento", "Câmera", "Categoria", "Horário", "Duração", "Status", "Evidência", "Ações"],
    row: eventRow,
    detail: eventDetail,
  },
  "/alerts": {
    title: "Alertas",
    section: "monitoring",
    breadcrumb: "Monitoramento / Alertas",
    permissions: [],
    heading: "Alertas",
    subtitle: "Alertas enviados, pendentes, resolvidos e regras.",
    endpoint: "/alert-deliveries",
    action: "Criar regra de alerta",
    actionHref: "/settings/cameras#destinatarios",
    emptyTitle: "Nenhum alerta registrado.",
    emptyDescription: "Configure destinatários para registrar entregas de alertas operacionais.",
    tabs: ["Todos", "Pendentes", "Enviados", "Resolvidos", "Regras"],
    filters: ["Status", "Destinatário", "Evento"],
    columns: ["Tipo", "Câmera", "Evento", "Destinatário", "Horário", "Status"],
    row: (delivery) => [
      delivery.is_test ? "Teste" : "E-mail",
      "—",
      delivery.evento_id || "Teste",
      delivery.destinatario || delivery.recipient_id || "—",
      delivery.sent_at || delivery.last_attempt_at || delivery.criado_em || "—",
      badge(alertStatusLabel(delivery.status)),
    ],
  },
  "/evidence": {
    title: "Evidências",
    section: "monitoring",
    breadcrumb: "Monitoramento / Evidências",
    permissions: [],
    heading: "Evidências",
    subtitle: "Biblioteca de registros visuais capturados em eventos.",
    endpoint: "/eventos",
    action: "Abrir eventos",
    actionHref: "/events",
    emptyTitle: "Nenhuma evidência salva.",
    emptyDescription: "Snapshots aparecerão aqui quando eventos relevantes forem registrados.",
    tabs: ["Grade", "Lista"],
    filters: ["Câmera", "Data", "Evento", "Área"],
    columns: ["Título", "Horário", "Duração", "Origem", "Status", "Abrir"],
    filterRows: (rows) => rows.filter((event) => event.midia_path),
    row: (event) => [eventTitle(event), event.inicio || "—", event.duracao ?? "—", event.camera_id || "—", badge(event.status || "Registrado"), evidenceLink(event)],
    card: evidenceCard,
  },
  "/rules": {
    title: "Regras",
    section: "monitoring",
    breadcrumb: "Monitoramento / Regras",
    permissions: [],
    heading: "Regras",
    subtitle: "Motor configurável para combinar entidades, zonas, estados e duração.",
    endpoint: "/visual-rules",
    action: "Configurar regra",
    actionType: "visual-rule",
    emptyTitle: "Nenhuma regra configurada.",
    emptyDescription: "Crie uma regra visual para transformar estados do vídeo em eventos e alertas.",
    tabs: ["Todas", "Ativas", "Inativas"],
    filters: ["Câmera", "Tipo", "Severidade"],
    columns: ["Regra", "Condição", "Câmera", "Duração", "Cooldown", "Status", "Ações"],
    row: (rule) => [
      `<strong>${rule.nome || rule.tipo_evento}</strong>`,
      rule.condicao?.type || rule.tipo_evento,
      rule.camera_id || "—",
      `${rule.tempo_minimo || 0}s`,
      `${rule.cooldown_seconds || 0}s`,
      badge(rule.ativo ? "Ativa" : "Inativa"),
      rowMenu(),
    ],
    detail: ruleDetail,
  },
  "/reports": {
    title: "Relatórios",
    section: "intelligence",
    breadcrumb: "Inteligência / Relatórios",
    permissions: [],
    heading: "Relatórios",
    subtitle: "Relatórios por período, câmera, área e evento.",
    endpoint: "/relatorios/diario",
    action: "Gerar relatório",
    emptyTitle: "Nenhum relatório gerado.",
    emptyDescription: "Organize eventos, duração e recorrência por período.",
    tabs: ["Hoje", "7 dias", "Câmera", "Evento"],
    filters: ["Período", "Câmera", "Área", "Evento"],
    columns: ["Indicador", "Valor"],
    transform: (payload) => Object.entries(payload || {}).map(([key, value]) => ({ key, value })),
    row: (item) => [item.key, typeof item.value === "object" ? JSON.stringify(item.value) : item.value ?? "—"],
  },
  "/insights": {
    title: "Insights",
    section: "intelligence",
    breadcrumb: "Inteligência / Insights",
    permissions: [],
    heading: "Insights",
    subtitle: "Padrões e recorrências encontrados no histórico.",
    endpoint: "/operations/summary",
    action: "Atualizar insights",
    emptyTitle: "Nenhum insight disponível.",
    emptyDescription: "A Campex mostrará padrões quando houver histórico operacional suficiente.",
    tabs: ["Todos", "Paradas", "Operador", "Câmera"],
    filters: ["Período", "Câmera", "Máquina"],
    columns: ["Insight", "Valor"],
    transform: (payload) => [
      Number(payload.percentual_atividade_estimada || 0) ? { name: "Atividade estimada", value: `${payload.percentual_atividade_estimada}%` } : null,
      Number(payload.maior_parada || 0) ? { name: "Maior parada", value: `${payload.maior_parada}s` } : null,
      Number(payload.tempo_ativa_sem_operador || 0) ? { name: "Ativa sem operador", value: `${payload.tempo_ativa_sem_operador}s` } : null,
    ].filter(Boolean),
    row: (item) => [item.name, item.value],
  },
  "/history": {
    title: "Histórico",
    section: "intelligence",
    breadcrumb: "Inteligência / Histórico",
    permissions: [],
    heading: "Histórico",
    subtitle: "Linha histórica de eventos e mudanças de estado.",
    endpoint: "/operations/events?limit=100&offset=0",
    emptyTitle: "Nenhum histórico encontrado.",
    emptyDescription: "As mudanças de estado aparecerão aqui conforme a Campex monitora a operação.",
    transform: (payload) => payload.events || [],
    tabs: ["Todos", "Máquina", "Operador", "Câmera"],
    filters: ["Período", "Tipo"],
    columns: ["Início", "Tipo", "Estado anterior", "Novo estado", "Duração"],
    row: (event) => [event.started_at || "—", event.event_type || "—", event.previous_state || "—", event.new_state || "—", event.duration_seconds ?? "—"],
  },
  "/integrations": {
    title: "Integrações",
    section: "platform",
    breadcrumb: "Plataforma / Integrações",
    permissions: [],
    heading: "Integrações",
    subtitle: "Conexões futuras com sistemas da operação.",
    endpoint: "/health",
    action: "Adicionar integração",
    tabs: ["Todas", "Ativas", "Futuras"],
    filters: ["Status"],
    columns: ["Integração", "Status", "Observação"],
    emptyTitle: "Nenhuma integração configurada.",
    emptyDescription: "Conecte a Campex aos sistemas utilizados pela operação.",
    transform: () => [],
    row: (item) => [item.name, badge(item.status), item.note],
  },
  "/users": {
    title: "Usuários",
    section: "platform",
    breadcrumb: "Plataforma / Usuários",
    permissions: [],
    heading: "Usuários",
    subtitle: "Equipe e permissões.",
    endpoint: "/auth/users",
    action: "Adicionar usuário",
    actionHref: "/settings/cameras#usuarios",
    emptyTitle: "Nenhum usuário cadastrado.",
    emptyDescription: "Cadastre usuários do cliente para organizar acessos e permissões.",
    tabs: ["Todos", "Admins", "Operadores", "Visualizadores"],
    filters: ["Função", "Status"],
    columns: ["Nome", "E-mail", "Função", "Status"],
    row: (user) => [user.nome || "—", user.email || "—", user.role || "—", badge(user.ativo ? "Ativo" : "Inativo")],
  },
  "/settings": {
    title: "Configurações",
    section: "platform",
    breadcrumb: "Plataforma / Configurações",
    permissions: [],
    heading: "Configurações",
    subtitle: "Preferências e atalhos de configuração do piloto local.",
    endpoint: "/health",
    action: "Configurar câmeras",
    actionHref: "/settings/cameras",
    emptyTitle: "Nenhuma configuração encontrada.",
    emptyDescription: "Abra uma área de configuração para ajustar o piloto local.",
    tabs: ["Geral", "Câmeras", "Notificações", "Conta"],
    filters: ["Área"],
    columns: ["Configuração", "Destino"],
    transform: () => [
      { name: "Câmeras", href: "/settings/cameras" },
      { name: "Notificações", href: "/settings/notifications" },
      { name: "Conta", href: "/settings/account" },
    ],
    row: (item) => [item.name, `<a class="cx-link" href="${item.href}">Abrir</a>`],
  },
  "/settings/cameras": {
    title: "Configurações de câmeras",
    section: "platform",
    breadcrumb: "Plataforma / Configurações / Câmeras",
    external: true,
  },
  "/settings/notifications": {
    title: "Notificações",
    section: "platform",
    breadcrumb: "Plataforma / Configurações / Notificações",
    permissions: [],
    heading: "Notificações",
    subtitle: "Configurações de destinatários e entregas de alertas.",
    endpoint: "/alert-recipients",
    action: "Adicionar destinatário",
    actionHref: "/settings/cameras#destinatarios",
    emptyTitle: "Nenhum destinatário cadastrado.",
    emptyDescription: "Cadastre responsáveis para receber alertas por e-mail.",
    tabs: ["Todos", "Ativos", "Inativos"],
    filters: ["E-mail", "Tipo de evento"],
    columns: ["Nome", "E-mail", "Status", "Teste"],
    transform: (payload) => Array.isArray(payload) ? payload : payload.recipients || [],
    row: (recipient) => [
      recipient.nome || "—",
      recipient.email || "—",
      badge(recipient.ativo ? "Ativo" : "Inativo"),
      `<button type="button" data-test-recipient="${recipient.id}">Enviar teste</button>`,
    ],
  },
  "/settings/account": {
    title: "Conta",
    section: "platform",
    breadcrumb: "Plataforma / Configurações / Conta",
    permissions: [],
    heading: "Conta",
    subtitle: "Preferências gerais da conta local.",
    endpoint: "/health",
    action: "Abrir configurações",
    actionHref: "/settings/cameras",
    emptyTitle: "Nenhum dado de conta disponível.",
    emptyDescription: "As preferências da conta local aparecerão aqui quando configuradas.",
    tabs: ["Geral", "Segurança", "Sistema"],
    filters: ["Status"],
    columns: ["Item", "Status"],
    transform: (payload) => [
      { name: "API local", status: payload.status || "ok" },
      { name: "Sessão", status: "Local" },
      { name: "Banco", status: "SQLite" },
    ],
    row: (item) => [item.name, badge(item.status)],
  },
};

async function requestJson(url, options) {
  const response = await fetch(url, { headers: { "Content-Type": "application/json" }, ...options });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : { detail: await response.text() };
  if (!response.ok) throw new Error(payload.detail || `Erro HTTP ${response.status}`);
  return payload;
}

async function authStatus() {
  return requestJson("/auth/status").catch(() => ({ authenticated: false, bootstrap: false }));
}

function badge(value) {
  const text = String(value || "—");
  const key = text.toLowerCase();
  const klass = key.includes("ativa") || key.includes("ativo") || key.includes("online") || key.includes("enviado") || key.includes("sent")
    ? "success"
    : key.includes("pend") || key.includes("config")
      ? "warning"
      : key.includes("sinal") || key.includes("offline") || key.includes("erro") || key.includes("fal")
        ? "danger"
        : "offline";
  return `<span class="cx-badge ${klass}">${text}</span>`;
}

function cameraStatusLabel(status) {
  if (status === "online") return "Ativa";
  if (status === "offline") return "Sem sinal";
  if (status === "nao_conectada" || status === "nao_testada") return "Em configuração";
  if (status === "inativa") return "Pausada";
  return status || "Em configuração";
}

function alertStatusLabel(status) {
  if (status === "sent") return "Enviado";
  if (status === "pending") return "Pendente";
  if (status === "failed") return "Pendente";
  return status || "Resolvido";
}

function eventTitle(event) {
  if (event.tipo === "machine_stoppage") return "Parada detectada";
  if (event.tipo === "restricted_area_occupied") return "Pessoa em área restrita";
  return event.tipo || event.event_type || "Evento operacional";
}

function eventCategory(event) {
  const text = `${event.tipo || event.event_type || ""}`.toLowerCase();
  if (text.includes("machine") || text.includes("stoppage")) return "Máquina";
  if (text.includes("person") || text.includes("restricted")) return "Pessoas";
  return "Operação";
}

function evidenceLink(event) {
  return event.midia_path ? `<a class="cx-link" href="/eventos/${event.id}/evidence" target="_blank">Abrir</a>` : "—";
}

function rowMenu() {
  return '<button class="cx-row-menu" type="button" data-open-detail>•••</button>';
}

function eventRow(event) {
  return [
    `<strong>${eventTitle(event)}</strong>`,
    event.camera_id || "—",
    eventCategory(event),
    event.inicio || event.criado_em || "—",
    event.duracao ?? "—",
    badge(event.status || "Registrado"),
    evidenceLink(event),
    rowMenu(),
  ];
}

function cameraCard(camera) {
  return `
    <article class="cx-camera-tile">
      <div class="cx-camera-thumb"><span class="cx-nav-icon" data-icon="camera"></span></div>
      <div><strong>${camera.nome || "Câmera"}</strong><span>${camera.unidade_id || "Localização não informada"}</span></div>
      ${badge(cameraStatusLabel(camera.status))}
      <p>Último evento: ${camera.ultimo_erro || "sem registro"}</p>
      <p>Atualização: ${camera.ultimo_frame || camera.criado_em || "—"}</p>
      <button class="cx-row-menu" type="button" data-open-detail>•••</button>
    </article>
  `;
}

function evidenceCard(event) {
  return `
    <article class="cx-camera-tile">
      <div class="cx-camera-thumb"><span class="cx-nav-icon" data-icon="evidence"></span></div>
      <div><strong>${eventTitle(event)}</strong><span>${event.inicio || "—"}</span></div>
      ${badge(event.status || "Registrado")}
      <p>Origem: ${event.camera_id || "—"}</p>
      ${evidenceLink(event)}
    </article>
  `;
}

function eventDetail(event) {
  return `
    <h2>${eventTitle(event)}</h2>
    <div class="cx-detail-frame">${event.midia_path ? `<img src="/eventos/${event.id}/evidence" alt="Frame da ocorrência" />` : "Sem frame disponível"}</div>
    <dl>
      <div><dt>Horário</dt><dd>${event.inicio || event.criado_em || "—"}</dd></div>
      <div><dt>Duração</dt><dd>${event.duracao ?? "—"}</dd></div>
      <div><dt>Câmera</dt><dd>${event.camera_id || "—"}</dd></div>
      <div><dt>Área</dt><dd>${event.area_id || "—"}</dd></div>
      <div><dt>Contexto</dt><dd>${event.tipo || "Evento operacional"}</dd></div>
      <div><dt>Alerta</dt><dd>${event.status || "Registrado"}</dd></div>
      <div><dt>Evidência</dt><dd>${event.midia_path ? "Disponível" : "—"}</dd></div>
    </dl>
  `;
}

function ruleDetail(rule) {
  return `
    <h2>${rule.nome || "Regra visual"}</h2>
    <dl>
      <div><dt>Câmera</dt><dd>${rule.camera_id || "—"}</dd></div>
      <div><dt>Tipo do evento</dt><dd>${rule.tipo_evento || "—"}</dd></div>
      <div><dt>Condição</dt><dd>${rule.condicao?.type || "—"}</dd></div>
      <div><dt>Duração mínima</dt><dd>${rule.tempo_minimo || 0}s</dd></div>
      <div><dt>Severidade</dt><dd>${rule.severidade || "medium"}</dd></div>
      <div><dt>Cooldown</dt><dd>${rule.cooldown_seconds || 0}s</dd></div>
      <div><dt>Alerta ao iniciar</dt><dd>${rule.alerta_inicio ? "Sim" : "Não"}</dd></div>
      <div><dt>Alerta ao normalizar</dt><dd>${rule.alerta_normalizacao ? "Sim" : "Não"}</dd></div>
      <div><dt>Status</dt><dd>${rule.ativo ? "Ativa" : "Inativa"}</dd></div>
    </dl>
    <pre>${JSON.stringify(rule.condicao || {}, null, 2)}</pre>
  `;
}

function visualRuleForm() {
  return `
    <h2>Configurar regra visual</h2>
    <form id="visualRuleForm" class="form">
      <label>Nome da regra<input name="nome" required placeholder="Ex.: Máquina ativa sem operador" /></label>
      <label>Câmera<input name="camera_id" required placeholder="ID da câmera cadastrada" /></label>
      <label>Tipo do evento<input name="tipo_evento" required value="active_without_operator" /></label>
      <label>Condição
        <select name="condition_type">
          <option value="all">Máquina ativa + ausência em zona</option>
          <option value="presence_in_zone">Presença em zona</option>
          <option value="absence_in_zone">Ausência em zona</option>
          <option value="count_between">Contagem mínima e máxima</option>
          <option value="machine_state">Estado da máquina</option>
          <option value="camera_status">Status da câmera</option>
          <option value="no_motion_in_region">Ausência de movimento</option>
        </select>
      </label>
      <label>Região ou zona<input name="regiao_id" placeholder="Ex.: operador, area_restrita_1" /></label>
      <label>Duração mínima em segundos<input name="tempo_minimo" type="number" min="0" step="1" value="120" /></label>
      <label>Severidade
        <select name="severidade">
          <option value="low">Baixa</option>
          <option value="medium">Média</option>
          <option value="high">Alta</option>
          <option value="critical">Crítica</option>
        </select>
      </label>
      <label>Cooldown em segundos<input name="cooldown_seconds" type="number" min="0" step="1" value="300" /></label>
      <label><input name="alerta_inicio" type="checkbox" checked /> Enviar alerta ao iniciar</label>
      <label><input name="alerta_normalizacao" type="checkbox" /> Enviar alerta ao normalizar</label>
      <button type="submit">Salvar regra</button>
      <p id="visualRuleStatus" class="muted">A regra será salva no banco local e poderá ser testada no modo simulação.</p>
    </form>
  `;
}

function conditionFromForm(data) {
  const type = data.get("condition_type");
  const zone = data.get("regiao_id") || undefined;
  if (type === "all") {
    return {
      type: "all",
      conditions: [
        { type: "machine_state", state: "ATIVA" },
        { type: "absence_in_zone", zone_id: zone || "operator", max_count: 0 },
      ],
    };
  }
  if (type === "presence_in_zone") return { type, zone_id: zone, min_count: 1 };
  if (type === "absence_in_zone") return { type, zone_id: zone, max_count: 0 };
  if (type === "count_between") return { type, field: "people_count", min: 1, max: 5 };
  if (type === "machine_state") return { type, state: "PARADA" };
  if (type === "camera_status") return { type, status: "offline" };
  if (type === "no_motion_in_region") return { type, zone_id: zone, max_motion: 0 };
  return { type };
}

function matchesTab(row) {
  const text = JSON.stringify(row).toLowerCase();
  if (currentTab === "all" || currentTab === "todas" || currentTab === "todos" || currentTab === "grade" || currentTab === "lista") return true;
  if (currentTab === "ativa") return cameraStatusLabel(row.status).toLowerCase() === "ativa";
  if (currentTab === "sem sinal") return cameraStatusLabel(row.status).toLowerCase() === "sem sinal";
  if (currentTab === "em configuração") return cameraStatusLabel(row.status).toLowerCase() === "em configuração";
  if (currentTab === "pausada") return cameraStatusLabel(row.status).toLowerCase() === "pausada";
  if (currentTab === "paradas") return text.includes("stoppage") || text.includes("parada");
  if (currentTab === "pessoas") return text.includes("restricted") || text.includes("pessoa");
  if (currentTab === "máquinas") return text.includes("machine") || text.includes("máquina");
  if (currentTab === "com evidência") return Boolean(row.midia_path || row.snapshot_path);
  if (currentTab === "pendentes") return text.includes("pending") || text.includes("failed");
  if (currentTab === "enviados") return text.includes("sent");
  return true;
}

function includesSearch(row) {
  const query = (search.value || "").trim().toLowerCase();
  if (!query) return true;
  return JSON.stringify(row).toLowerCase().includes(query);
}

function renderTabs(config) {
  tabs.innerHTML = (config.tabs || []).map((tab, index) => `<button type="button" class="${index === 0 ? "active" : ""}" data-tab="${tab.toLowerCase()}">${tab}</button>`).join("");
  currentTab = (config.tabs?.[0] || "all").toLowerCase();
}

function renderFilters(config) {
  filters.innerHTML = (config.filters || []).map((label) => `
    <label>${label}<input placeholder="${label}" data-filter="${label}" /></label>
  `).join("");
}

function currentRouteConfig() {
  return routes[window.location.pathname] || routes["/cameras"];
}

function activeRouteKey(path = window.location.pathname) {
  if (path === "/settings" || path.startsWith("/settings/")) return "/settings/cameras";
  if (path === "/" || path === "/dashboard") return "/dashboard";
  return path;
}

function emptyState(config) {
  const action = config.actionHref
    ? `<a class="cx-primary-action" href="${config.actionHref}">${config.action || "Abrir"}</a>`
    : `<button type="button">${config.action || "Atualizar"}</button>`;
  return `
    <div class="cx-empty-state">
      <strong>${config.emptyTitle || `Nenhum registro em ${config.title}.`}</strong>
      <p>${config.emptyDescription || "Os dados aparecerão aqui quando forem registrados pela Campex."}</p>
      ${config.action ? action : ""}
    </div>
  `;
}

function loginState(config) {
  return `
    <div class="cx-empty-state">
      <strong>Login necessário</strong>
      <p>Entre para carregar ${String(config.title || "esta área").toLowerCase()} e proteger os dados do cliente.</p>
      <a class="cx-primary-action" href="/settings/cameras#login">Entrar</a>
    </div>
  `;
}

function renderRows(config) {
  const rows = rowsCache.filter(matchesTab).filter(includesSearch);
  head.innerHTML = `<tr>${config.columns.map((column) => `<th>${column}</th>`).join("")}</tr>`;
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="${config.columns.length}">${emptyState(config)}</td></tr>`;
  } else {
    body.innerHTML = rows.map((row, index) => `<tr data-row-index="${index}">${config.row(row).map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("");
  }
  const path = window.location.pathname;
  const useGrid = config.card && (viewMode === "grid" || path === "/cameras" || path === "/evidence");
  grid.style.display = useGrid ? "grid" : "none";
  grid.innerHTML = useGrid ? rows.map(config.card).join("") : "";
}

function renderNotFound(path = window.location.pathname) {
  const config = {
    title: "Página não encontrada",
    heading: "Página não encontrada",
    subtitle: "O endereço acessado não corresponde a nenhuma área da plataforma.",
    columns: ["Mensagem"],
    action: "Voltar para a Home",
    actionHref: "/dashboard",
    emptyTitle: "Página não encontrada",
    emptyDescription: "O endereço acessado não corresponde a nenhuma área da plataforma.",
  };
  document.title = "Página não encontrada | Campex";
  title.textContent = config.title;
  heading.textContent = config.heading;
  subtitle.textContent = `${config.subtitle} (${path})`;
  tableTitle.textContent = config.title;
  tableHint.textContent = "Verifique o endereço ou volte para a Home.";
  cards.innerHTML = [
    `<article><strong>404</strong><span>Rota inválida</span></article>`,
    `<article><strong>Campex</strong><span>Shell carregado</span></article>`,
    `<article><strong>Seguro</strong><span>Nenhuma API foi substituída</span></article>`,
  ].join("");
  renderTabs({ tabs: [] });
  renderFilters({ filters: [] });
  rowsCache = [];
  grid.style.display = "none";
  head.innerHTML = "<tr><th>Mensagem</th></tr>";
  body.innerHTML = `<tr><td>${emptyState(config)}</td></tr>`;
  primaryAction.textContent = "Voltar para a Home";
  primaryAction.onclick = () => { window.location.href = "/dashboard"; };
  document.querySelectorAll("[data-route], .cx-nav a").forEach((link) => {
    link.classList.remove("active");
    link.setAttribute("aria-current", "false");
  });
}

function openDrawer(row, config) {
  drawer.classList.add("open");
  drawer.setAttribute("aria-hidden", "false");
  drawerContent.innerHTML = config.detail ? config.detail(row) : `<h2>${config.title}</h2><pre>${JSON.stringify(row, null, 2)}</pre>`;
  drawer.querySelector("h2")?.setAttribute("id", "workspaceDrawerTitle");
  drawer.focus({ preventScroll: true });
}

async function loadPage(path = window.location.pathname) {
  const config = routes[path];
  if (!config) {
    renderNotFound(path);
    return;
  }
  if (config.external) {
    window.location.href = path;
    return;
  }
  rowsCache = [];
  viewMode = "grid";
  closeSidePanels();
  closeDrawer();
  document.querySelectorAll("[data-route], .cx-nav a").forEach((link) => {
    const href = link.dataset.route || new URL(link.href, window.location.origin).pathname;
    const active = activeRouteKey(href) === activeRouteKey(path);
    link.classList.toggle("active", active);
    link.setAttribute("aria-current", active ? "page" : "false");
    const label = link.textContent.trim();
    link.setAttribute("title", label);
    link.setAttribute("aria-label", label);
  });
  document.title = `${config.title} | Campex`;
  title.textContent = config.title;
  heading.textContent = config.heading;
  subtitle.textContent = config.subtitle;
  tableTitle.textContent = config.title;
  tableHint.textContent = config.subtitle;
  primaryAction.textContent = config.action || "Nova ação";
  primaryAction.onclick = () => {
    if (config.actionType === "visual-rule") {
      drawer.classList.add("open");
      drawer.setAttribute("aria-hidden", "false");
      drawerContent.innerHTML = visualRuleForm();
      drawer.querySelector("h2")?.setAttribute("id", "workspaceDrawerTitle");
      drawer.focus({ preventScroll: true });
      return;
    }
    if (config.actionHref) window.location.href = config.actionHref;
    else openPopover(primaryAction, config.action || "Ação futura", ["Recurso futuro do piloto", "Nenhuma alteração feita"]);
  };
  cards.innerHTML = [
    `<article><strong id="workspaceCount">—</strong><span>Registros</span></article>`,
    `<article><strong>Local</strong><span>SQLite persistente</span></article>`,
    `<article><strong>Seguro</strong><span>Sem credenciais no navegador</span></article>`,
  ].join("");
  renderTabs(config);
  renderFilters(config);
  try {
    const auth = await authStatus();
    if (!auth.authenticated && !auth.bootstrap && config.endpoint !== "/health") {
      rowsCache = [];
      document.querySelector("#workspaceCount").textContent = "—";
      head.innerHTML = `<tr>${config.columns.map((column) => `<th>${column}</th>`).join("")}</tr>`;
      body.innerHTML = `<tr><td colspan="${config.columns.length}">${loginState(config)}</td></tr>`;
      grid.style.display = "none";
      document.querySelector(".cx-main")?.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }
    const payload = await requestJson(config.endpoint);
    let rows = config.transform ? config.transform(payload) : Array.isArray(payload) ? payload : payload.events || payload.deliveries || payload.recipients || payload.machines || [];
    rows = Array.isArray(rows) ? rows : [];
    rowsCache = config.filterRows ? config.filterRows(rows) : rows;
    document.querySelector("#workspaceCount").textContent = rowsCache.length;
    renderRows(config);
  } catch (error) {
    body.innerHTML = `<tr><td>Não foi possível carregar: ${error.message}</td></tr>`;
  }
  document.querySelector(".cx-main")?.scrollTo({ top: 0, behavior: "smooth" });
}

function navigateTo(path) {
  if (!routes[path]) {
    window.location.href = path;
    return;
  }
  if (routes[path].external) {
    window.location.href = path;
    return;
  }
  if (window.location.pathname !== path) {
    window.history.pushState({ path }, "", path);
  }
  loadPage(path);
}

tabs.addEventListener("click", (event) => {
  const button = event.target.closest("[data-tab]");
  if (!button) return;
  tabs.querySelectorAll("button").forEach((item) => item.classList.remove("active"));
  button.classList.add("active");
  currentTab = button.dataset.tab;
  viewMode = currentTab === "lista" ? "list" : currentTab === "grade" ? "grid" : viewMode;
  renderRows(currentRouteConfig());
});

document.body.addEventListener("click", async (event) => {
  const link = event.target.closest("a[href]");
  if (link) {
    const url = new URL(link.href, window.location.origin);
    const sameOrigin = url.origin === window.location.origin;
    const route = routes[url.pathname];
    if (sameOrigin && route && !route.external && !link.target && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) {
      event.preventDefault();
      navigateTo(url.pathname);
      return;
    }
  }

  const testButton = event.target.closest("[data-test-recipient]");
  if (testButton) {
    testButton.textContent = "Enviando...";
    try {
      await requestJson(`/alert-recipients/${testButton.dataset.testRecipient}/test`, { method: "POST" });
      testButton.textContent = "Enviado";
    } catch (error) {
      testButton.textContent = `Erro`;
    }
    return;
  }
  const ruleForm = event.target.closest("#visualRuleForm");
  if (ruleForm && event.type === "submit") return;
  const row = event.target.closest("[data-row-index]");
  const menu = event.target.closest("[data-open-detail]");
  if (!row && !menu) return;
  const index = row ? Number(row.dataset.rowIndex) : 0;
  openDrawer(rowsCache.filter(matchesTab).filter(includesSearch)[index] || rowsCache[0], currentRouteConfig());
});

document.body.addEventListener("submit", async (event) => {
  const form = event.target.closest("#visualRuleForm");
  if (!form) return;
  event.preventDefault();
  const status = form.querySelector("#visualRuleStatus");
  const data = new FormData(form);
  const payload = {
    nome: data.get("nome"),
    camera_id: data.get("camera_id"),
    tipo_evento: data.get("tipo_evento"),
    regiao_id: data.get("regiao_id") || null,
    tempo_minimo: Number(data.get("tempo_minimo") || 0),
    severidade: data.get("severidade"),
    cooldown_seconds: Number(data.get("cooldown_seconds") || 0),
    alerta_inicio: Boolean(data.get("alerta_inicio")),
    alerta_normalizacao: Boolean(data.get("alerta_normalizacao")),
    condicao: conditionFromForm(data),
    ativo: true,
  };
  status.textContent = "Salvando regra...";
  try {
    await requestJson("/visual-rules", { method: "POST", body: JSON.stringify(payload) });
    status.textContent = "Regra salva.";
    await loadPage("/rules");
    drawer.classList.remove("open");
    drawer.setAttribute("aria-hidden", "true");
  } catch (error) {
    status.textContent = `Erro ao salvar: ${error.message}`;
  }
});

drawerClose.addEventListener("click", () => {
  drawer.classList.remove("open");
  drawer.setAttribute("aria-hidden", "true");
});

search.addEventListener("input", () => renderRows(currentRouteConfig()));
window.addEventListener("popstate", () => loadPage(window.location.pathname));
loadPage();
