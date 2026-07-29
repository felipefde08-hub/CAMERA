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
    subtitle: "Ocorrências operacionais com duração, severidade, evidência, alerta e responsável.",
    endpoint: "/eventos",
    action: "Exportar eventos",
    emptyTitle: "Nenhum evento registrado.",
    emptyDescription: "Os eventos aparecerão aqui quando a operação gerar histórico.",
    tabs: ["Todos", "Aberto", "Em análise", "Reconhecido", "Encerrado", "Descartado", "Com evidência"],
    filters: ["Período", "Tipo", "Categoria", "Unidade", "Área", "Câmera", "Severidade", "Status", "Evidência", "Alerta"],
    columns: ["Data e hora", "Tipo", "Categoria", "Unidade", "Área", "Câmera", "Máquina/equipamento", "Duração", "Severidade", "Status", "Evidência", "Alerta", "Responsável", "Ação"],
    row: eventRow,
    detail: eventDetail,
  },
  "/alerts": {
    title: "Alertas",
    section: "monitoring",
    breadcrumb: "Monitoramento / Alertas",
    permissions: [],
    heading: "Alertas",
    subtitle: "Configuração e histórico de entregas de alertas, sem misturar falha de envio com evento aguardando análise.",
    endpoint: "/alert-deliveries",
    action: "Criar regra de alerta",
    actionHref: "/settings/cameras#destinatarios",
    emptyTitle: "Nenhum alerta registrado.",
    emptyDescription: "Configure destinatários para registrar entregas de alertas operacionais.",
    tabs: ["Regras de alerta", "Destinatários", "Entregas", "Falhas"],
    filters: ["Evento", "Severidade", "Destinatário", "Canal", "Status", "Falha"],
    columns: ["Evento", "Destinatário", "Canal", "Horário", "Resultado", "Tentativas", "Erro", "Status", "Ações"],
    load: loadAlertsWorkspace,
    row: alertRow,
    detail: alertDeliveryDetail,
  },
  "/evidence": {
    title: "Evidências",
    section: "monitoring",
    breadcrumb: "Monitoramento / Evidências",
    permissions: [],
    heading: "Evidências",
    subtitle: "Biblioteca operacional de snapshots associados a eventos reais.",
    endpoint: "/eventos",
    action: "Abrir eventos",
    actionHref: "/events",
    emptyTitle: "Nenhuma evidência salva.",
    emptyDescription: "As evidências serão exibidas quando um evento configurado registrar uma ocorrência visual.",
    tabs: ["Grade", "Lista"],
    filters: ["Período", "Evento", "Categoria", "Área", "Câmera", "Severidade", "Retenção"],
    columns: ["Snapshot", "Evento", "Horário", "Unidade", "Área", "Câmera", "Tipo", "Severidade", "Duração", "Retenção", "Status", "Abrir"],
    filterRows: (rows) => rows.filter((event) => event.midia_path || event.snapshot_path),
    row: evidenceRow,
    card: evidenceCard,
    detail: evidenceDetail,
  },
  "/rules": {
    title: "Regras",
    section: "monitoring",
    breadcrumb: "Monitoramento / Regras",
    permissions: [],
    heading: "Regras",
    subtitle: "Construtor operacional de regras visuais em linguagem de operação.",
    endpoint: "/visual-rules",
    action: "Configurar regra",
    actionType: "visual-rule",
    emptyTitle: "Nenhuma regra configurada.",
    emptyDescription: "Crie uma regra visual para transformar estados do vídeo em eventos e alertas.",
    tabs: ["Todas", "Ativas", "Inativas", "Em desenvolvimento"],
    filters: ["Unidade", "Câmera", "Área", "Condição", "Severidade", "Status"],
    columns: ["Nome", "Unidade", "Câmera", "Área/zona", "Condição", "Tempo mínimo", "Severidade", "Cooldown", "Alerta", "Status", "Última ativação", "Ações"],
    row: (rule) => [
      `<strong>${rule.nome || rule.tipo_evento}</strong>`,
      rule.unidade_id || "—",
      rule.camera_id || "—",
      rule.regiao_id || rule.area_id || "—",
      humanCondition(rule),
      `${rule.tempo_minimo || 0}s`,
      badge(rule.severidade || "medium"),
      `${rule.cooldown_seconds || 0}s`,
      rule.alerta_inicio || rule.alerta_normalizacao ? "Configurado" : "Sem alerta",
      badge(rule.ativo ? "Ativa" : "Inativa"),
      rule.last_triggered_at || rule.ultima_ativacao || "—",
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
    subtitle: "Leitura gerencial por período, unidade, áreas, categorias, alertas e evidências.",
    endpoint: "/relatorios/diario",
    action: "Gerar relatório",
    emptyTitle: "Nenhum relatório gerado.",
    emptyDescription: "Organize eventos, duração e recorrência por período.",
    tabs: ["Resumo operacional", "Eventos por período", "Duração", "Disponibilidade", "Área", "Alertas", "Evidências"],
    filters: ["Período", "Unidade", "Áreas", "Categorias", "Formato"],
    columns: ["Relatório", "Período", "Criado em", "Responsável", "Status", "Formato", "Ação"],
    transform: (payload) => Object.entries(payload || {}).map(([key, value]) => ({ key, value })),
    row: (item) => [reportLabel(item.key), "Período atual", "—", "—", badge(item.value ? "Prévia" : "Sem dados"), "Tela", typeof item.value === "object" ? JSON.stringify(item.value) : item.value ?? "—"],
  },
  "/insights": {
    title: "Insights",
    section: "intelligence",
    breadcrumb: "Inteligência / Insights",
    permissions: [],
    heading: "Insights",
    subtitle: "Padrões gerados somente quando há dados suficientes para sustentar a constatação.",
    endpoint: "/operations/summary",
    action: "Atualizar insights",
    emptyTitle: "Ainda não existem dados suficientes para gerar padrões confiáveis.",
    emptyDescription: "A Campex só apresenta insights quando há ocorrências suficientes, período definido e base comparável.",
    tabs: ["Todos", "Recorrência", "Duração", "Horário", "Câmera", "Comparação"],
    filters: ["Período", "Categoria", "Área", "Câmera", "Confiança"],
    columns: ["Constatação", "Dados utilizados", "Período", "Confiança", "Investigar"],
    load: loadInsightsWorkspace,
    row: (item) => [item.statement, item.data, item.period, badge(item.confidence), `<a class="cx-link" href="${item.href}">Investigar</a>`],
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
    subtitle: "Equipe, convites e permissões vinculadas ao cliente.",
    endpoint: "/auth/users",
    action: "Convidar usuário",
    actionHref: "/settings/cameras#usuarios",
    emptyTitle: "Nenhum usuário cadastrado.",
    emptyDescription: "O administrador convida usuários; a identidade é vinculada ao cliente e as permissões são aplicadas.",
    tabs: ["Todos", "Admins", "Operadores", "Visualizadores"],
    filters: ["Função", "Cliente", "Unidade", "Status"],
    columns: ["Nome", "E-mail", "Função", "Cliente", "Unidades", "Status", "Último acesso"],
    row: (user) => [
      user.nome || "—",
      user.email || "—",
      user.role || "—",
      user.cliente_id || "Cliente vinculado",
      user.unidades?.join?.(", ") || "Conforme permissão",
      badge(user.ativo ? "Ativo" : "Inativo"),
      user.ultimo_acesso || "—",
    ],
  },
  "/settings": {
    title: "Configurações",
    section: "platform",
    breadcrumb: "Plataforma / Configurações",
    permissions: [],
    heading: "Configurações",
    subtitle: "Empresa, unidades, usuários, câmeras, máquinas, alertas, segurança e retenção.",
    endpoint: "/health",
    action: "Configurar câmeras",
    actionHref: "/settings/cameras",
    emptyTitle: "Nenhuma configuração encontrada.",
    emptyDescription: "Abra uma área de configuração para ajustar o piloto local.",
    tabs: ["Empresa", "Unidades", "Usuários", "Câmeras", "Máquinas e áreas", "Alertas", "Integrações", "Segurança", "Retenção"],
    filters: ["Área"],
    columns: ["Configuração", "Destino"],
    transform: () => [
      { name: "Empresa", href: "/settings/cameras#clientes", note: "Cliente, documento e status." },
      { name: "Unidades", href: "/settings/cameras#unidades", note: "Unidades operacionais vinculadas ao cliente." },
      { name: "Usuários", href: "/users", note: "Convites, permissões e vínculo ao cliente." },
      { name: "Câmeras", href: "/settings/cameras" },
      { name: "Máquinas e áreas", href: "/settings/cameras#maquinas", note: "Zonas e parâmetros de calibração." },
      { name: "Alertas", href: "/settings/notifications", note: "Destinatários e entregas." },
      { name: "Integrações", href: "/integrations", note: "Conexões futuras com sistemas da operação." },
      { name: "Segurança", href: "/settings/account", note: "Sessão, credenciais protegidas e acesso local." },
      { name: "Retenção de evidências", href: "/evidence", note: "Política local de snapshots." },
    ],
    row: (item) => [item.name, `<span>${item.note || "Configuração do piloto local."}</span> <a class="cx-link" href="${item.href}">Abrir</a>`],
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
  "/help": {
    title: "Ajuda",
    section: "support",
    breadcrumb: "Suporte / Ajuda",
    permissions: [],
    heading: "Ajuda",
    subtitle: "Orientações para operar o piloto local da Campex.",
    endpoint: "/health",
    action: "Abrir configurações",
    actionHref: "/settings/cameras",
    emptyTitle: "Central de ajuda local",
    emptyDescription: "Use esta área para revisar os próximos passos: cadastrar câmera, validar eventos, revisar evidências e configurar alertas.",
    tabs: ["Primeiros passos", "Conectar câmera", "Configurar zona", "Criar regra", "Configurar alerta", "Revisar evento", "Evidências", "Problemas", "Diagnóstico", "Contato"],
    filters: ["Tema", "Status"],
    columns: ["Tema", "Orientação", "Status", "Ação"],
    load: loadHelpWorkspace,
    row: (item) => [item.name, item.note, badge(item.status || "Disponível"), item.href ? `<a class="cx-link" href="${item.href}">Abrir</a>` : "—"],
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
  const klass = key.includes("ativa") || key.includes("ativo") || key.includes("online") || key.includes("enviado") || key.includes("sent") || key.includes("disponível") || key.includes("sem falhas")
    ? "success"
      : key.includes("pend") || key.includes("config") || key.includes("atenção")
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
  if (status === "pending") return "Em processamento";
  if (status === "failed") return "Falha de entrega";
  return status || "Resolvido";
}

async function loadAlertsWorkspace() {
  const [deliveries, recipients, rules] = await Promise.all([
    requestJson("/alert-deliveries").catch(() => []),
    requestJson("/alert-recipients").catch(() => []),
    requestJson("/visual-rules").catch(() => []),
  ]);
  const deliveryRows = (Array.isArray(deliveries) ? deliveries : deliveries.deliveries || []).map((item) => ({ ...item, workspace_kind: "entrega" }));
  const recipientRows = (Array.isArray(recipients) ? recipients : recipients.recipients || []).map((item) => ({ ...item, workspace_kind: "destinatario" }));
  const ruleRows = (Array.isArray(rules) ? rules : rules.rules || []).map((item) => ({ ...item, workspace_kind: "regra" }));
  return [...ruleRows, ...recipientRows, ...deliveryRows];
}

async function loadInsightsWorkspace() {
  const [summary, eventsPayload, operationsPayload] = await Promise.all([
    requestJson("/operations/summary").catch(() => ({})),
    requestJson("/operations/events?limit=200&offset=0").catch(() => ({ events: [] })),
    requestJson("/operations").catch(() => ({ machines: [] })),
  ]);
  const events = eventsPayload.events || [];
  const insights = [];
  if (events.length < 3) return insights;

  const byType = countBy(events, (event) => event.event_type || event.tipo || "Evento operacional");
  const topType = topEntry(byType);
  if (topType && topType[1] >= 2) {
    insights.push({
      statement: `${topType[0]} se repetiu ${topType[1]} vezes no período.`,
      data: `${topType[1]} de ${events.length} ocorrências`,
      period: "Período atual",
      confidence: `${topType[1]} ocorrências`,
      href: "/history",
    });
  }

  const byArea = sumBy(events, (event) => event.machine_name || event.area_id || event.camera_id || "Sem área", (event) => Number(event.duration_seconds || event.duracao || 0));
  const topArea = topEntry(byArea);
  const totalDuration = Array.from(byArea.values()).reduce((sum, value) => sum + value, 0);
  if (topArea && totalDuration > 0 && topArea[1] / totalDuration >= 0.35) {
    insights.push({
      statement: `${topArea[0]} concentrou ${Math.round((topArea[1] / totalDuration) * 100)}% da duração total das ocorrências.`,
      data: `${Math.round(topArea[1])}s de ${Math.round(totalDuration)}s`,
      period: "Período atual",
      confidence: `${events.length} eventos`,
      href: "/events",
    });
  }

  const byHour = countBy(events, (event) => {
    const date = new Date(event.started_at || event.inicio || event.criado_em || "");
    return Number.isNaN(date.getTime()) ? "Sem horário" : `${String(date.getHours()).padStart(2, "0")}:00`;
  });
  const topHour = topEntry(byHour);
  if (topHour && topHour[1] >= 2 && topHour[0] !== "Sem horário") {
    insights.push({
      statement: `${topHour[0]} foi o horário com maior concentração de ocorrências.`,
      data: `${topHour[1]} ocorrências`,
      period: "Período atual",
      confidence: `${topHour[1]} ocorrências`,
      href: "/events",
    });
  }

  const offlineSeconds = Number(summary.tempo_total_monitorado || 0) * (1 - Number(summary.disponibilidade_camera || 100) / 100);
  if (offlineSeconds >= 60) {
    insights.push({
      statement: `Houve indisponibilidade estimada de câmera no período.`,
      data: `${Math.round(offlineSeconds)}s offline estimados`,
      period: "Período atual",
      confidence: summary.disponibilidade_camera ? `${summary.disponibilidade_camera}% disponibilidade` : "baixo",
      href: "/cameras",
    });
  }

  const machines = operationsPayload.machines || [];
  const unavailableMachines = machines.filter((item) => item.monitor?.current_state === "unavailable");
  if (unavailableMachines.length) {
    insights.push({
      statement: `${unavailableMachines.length} operação(ões) estão sem estado operacional disponível.`,
      data: "Estados atuais de máquinas/áreas",
      period: "Agora",
      confidence: `${unavailableMachines.length} registros`,
      href: "/overview",
    });
  }

  return insights;
}

async function loadHelpWorkspace() {
  const [health, systemHealth, cameras, deliveries] = await Promise.all([
    requestJson("/health").catch(() => ({ status: "erro" })),
    requestJson("/system/health").catch(() => ({})),
    requestJson("/cameras/estado").catch(() => []),
    requestJson("/alert-deliveries").catch(() => []),
  ]);
  const onlineCameras = cameras.filter((camera) => camera.status === "online").length;
  const failedDeliveries = deliveries.filter((delivery) => delivery.status === "failed").length;
  return [
    { name: "Primeiros passos", note: "Conecte uma câmera, configure uma zona, crie uma regra e valide os primeiros eventos.", status: "Disponível", href: "/settings/cameras" },
    { name: "Conectar câmera", note: "Cadastre o RTSP no backend. A senha fica protegida e não aparece no navegador.", status: "Disponível", href: "/settings/cameras" },
    { name: "Configurar zona", note: "Abra Live View, desenhe a área, revise os pontos e salve a configuração.", status: "Disponível", href: "/live-view" },
    { name: "Criar regra", note: "Use Regras para definir condição, duração mínima, severidade, cooldown e alertas.", status: "Disponível", href: "/rules" },
    { name: "Configurar alerta", note: "Cadastre destinatários e acompanhe entregas, falhas e testes.", status: failedDeliveries ? "Atenção" : "Disponível", href: "/alerts" },
    { name: "Revisar evento", note: "Abra Eventos, confira snapshot, timeline, metadados e reconheça quando analisado.", status: "Disponível", href: "/events" },
    { name: "Entender evidências", note: "Snapshots aparecem apenas quando eventos configurados registram ocorrência visual.", status: "Disponível", href: "/evidence" },
    { name: "Solução de problemas", note: "Verifique câmera online, último frame, API local, banco e entregas de alerta.", status: "Disponível", href: "/help" },
    { name: "Backend", note: `API local: ${health.status || "indisponível"}`, status: health.status === "ok" ? "Online" : "Atenção" },
    { name: "Banco", note: systemHealth.database || systemHealth.banco || "SQLite local configurado", status: "Local" },
    { name: "Câmera", note: `${onlineCameras} câmera(s) online de ${cameras.length}`, status: onlineCameras ? "Online" : "Sem histórico recente", href: "/cameras" },
    { name: "Último frame", note: latestFrameText(cameras), status: cameras.length ? "Disponível" : "Sem dados" },
    { name: "Processamento", note: "Status de IA e regras aparece por câmera na Live View e no status operacional.", status: "Local" },
    { name: "Alertas", note: `${failedDeliveries} falha(s) de entrega registradas`, status: failedDeliveries ? "Atenção" : "Sem falhas", href: "/alerts" },
    { name: "Armazenamento", note: "Snapshots e banco ficam no diretório local de dados da instalação.", status: "Local" },
    { name: "Contato com a Campex", note: "Use o acompanhamento assistido do piloto para suporte técnico e validação operacional.", status: "Assistido" },
  ];
}

function countBy(items, keyFn) {
  const map = new Map();
  items.forEach((item) => {
    const key = keyFn(item);
    map.set(key, (map.get(key) || 0) + 1);
  });
  return map;
}

function sumBy(items, keyFn, valueFn) {
  const map = new Map();
  items.forEach((item) => {
    const key = keyFn(item);
    map.set(key, (map.get(key) || 0) + valueFn(item));
  });
  return map;
}

function topEntry(map) {
  return Array.from(map.entries()).sort((a, b) => b[1] - a[1])[0];
}

function latestFrameText(cameras) {
  const values = cameras.map((camera) => camera.ultimo_frame).filter(Boolean).sort().reverse();
  return values[0] || "Nenhum frame recente informado";
}

function alertRow(item) {
  if (item.workspace_kind === "regra") {
    return [
      item.tipo_evento || item.nome || "Regra",
      item.destinatarios || "Destinatários configurados por cliente",
      item.canais || "e-mail",
      item.last_triggered_at || "—",
      item.alerta_inicio ? "Ao iniciar" : item.alerta_normalizacao ? "Ao normalizar" : "Sem envio",
      item.cooldown_seconds || 0,
      "—",
      badge(item.ativo ? "Ativa" : "Inativa"),
      rowMenu(),
    ];
  }
  if (item.workspace_kind === "destinatario") {
    return [
      item.event_types?.join?.(", ") || "Tipos configurados",
      `${item.nome || "—"} · ${item.email || "—"}`,
      "e-mail",
      "—",
      item.ativo ? "Disponível" : "Pausado",
      "—",
      "—",
      badge(item.ativo ? "Ativo" : "Inativo"),
      `<button type="button" data-test-recipient="${item.id}">Enviar teste</button>`,
    ];
  }
  return [
    item.evento_id || "Teste",
    item.destinatario || item.recipient_id || "—",
    item.channel || item.canal || "e-mail",
    item.sent_at || item.last_attempt_at || item.criado_em || "—",
    item.status === "sent" ? "Entregue" : item.status === "failed" ? "Falha" : "Em processamento",
    item.attempts || item.tentativas || 1,
    item.erro || item.error || "—",
    badge(alertStatusLabel(item.status)),
    item.status === "failed" ? '<button type="button" class="cx-row-menu" data-open-detail>•••</button>' : rowMenu(),
  ];
}

function eventStatusLabel(status) {
  if (status === "open") return "Aberto";
  if (status === "analysis" || status === "em_analise") return "Em análise";
  if (status === "acknowledged") return "Reconhecido";
  if (status === "closed") return "Encerrado";
  if (status === "discarded" || status === "false_positive") return "Descartado";
  return status || "Aberto";
}

function eventSeverity(event) {
  const severity = String(event.severidade || event.severity || "").toLowerCase();
  if (severity) return severity;
  const text = `${event.tipo || ""} ${event.event_type || ""} ${event.new_state || ""}`.toLowerCase();
  if (text.includes("offline") || text.includes("parada") || text.includes("stoppage")) return "alta";
  if (text.includes("restricted") || text.includes("sem_operador")) return "média";
  return "normal";
}

function eventStart(event) {
  return event.inicio || event.started_at || event.criado_em || "—";
}

function eventEnd(event) {
  return event.fim || event.ended_at || "—";
}

function eventDuration(event) {
  return event.duracao ?? event.duration_seconds ?? "—";
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

function unitForEvent(event) {
  return event.unidade_id || event.unit_id || "—";
}

function evidenceLink(event) {
  return event.midia_path || event.snapshot_path ? `<a class="cx-link" href="/eventos/${event.id}/evidence" target="_blank">Abrir</a>` : "—";
}

function rowMenu() {
  return '<button class="cx-row-menu" type="button" data-open-detail>•••</button>';
}

function eventRow(event) {
  return [
    eventStart(event),
    `<strong>${eventTitle(event)}</strong>`,
    eventCategory(event),
    event.unidade_id || event.unit_id || "—",
    event.area_id || event.regiao_id || "—",
    event.camera_id || "—",
    event.machine_name || event.maquina || "—",
    eventDuration(event),
    badge(eventSeverity(event)),
    badge(eventStatusLabel(event.status)),
    evidenceLink(event),
    event.alert_sent || event.alerta_enviado ? "Enviado" : "—",
    event.responsavel || event.owner || "—",
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
      <div><strong>${eventTitle(event)}</strong><span>${eventStart(event)}</span></div>
      ${badge(eventSeverity(event))}
      <p>Origem: ${event.camera_id || "—"}</p>
      ${evidenceLink(event)}
    </article>
  `;
}

function evidenceRow(event) {
  return [
    event.midia_path || event.snapshot_path ? "Disponível" : "—",
    eventTitle(event),
    eventStart(event),
    event.unidade_id || "—",
    event.area_id || event.regiao_id || "—",
    event.camera_id || "—",
    eventCategory(event),
    badge(eventSeverity(event)),
    eventDuration(event),
    event.retention || "Política local",
    badge(eventStatusLabel(event.status)),
    evidenceLink(event),
  ];
}

function eventTimelineSteps(event) {
  return [
    eventStart(event) !== "—" ? ["Situação iniciada", eventStart(event)] : null,
    event.confirmed_at ? ["Condição confirmada", event.confirmed_at] : null,
    event.id ? ["Evento criado", event.criado_em || eventStart(event)] : null,
    event.midia_path || event.snapshot_path ? ["Evidência salva", "Disponível"] : null,
    event.alert_sent || event.alerta_enviado ? ["Alerta enviado", "Registrado"] : null,
    event.status === "acknowledged" ? ["Reconhecido", event.acknowledged_at || "—"] : null,
    eventEnd(event) !== "—" ? ["Normalizado", eventEnd(event)] : null,
    ["closed", "discarded"].includes(event.status) ? ["Encerrado", eventEnd(event)] : null,
  ].filter(Boolean);
}

function renderTimelineList(steps) {
  if (!steps.length) return "<p>Sem etapas registradas.</p>";
  return `<ol class="cx-event-timeline">${steps.map(([label, value]) => `<li><strong>${label}</strong><span>${value}</span></li>`).join("")}</ol>`;
}

function eventDetail(event) {
  return `
    <h2>${eventTitle(event)}</h2>
    <div class="cx-detail-frame">${event.midia_path || event.snapshot_path ? `<img src="/eventos/${event.id}/evidence" alt="Frame da ocorrência" />` : "Sem snapshot disponível"}</div>
    <dl>
      <div><dt>Horário inicial</dt><dd>${eventStart(event)}</dd></div>
      <div><dt>Horário final</dt><dd>${eventEnd(event)}</dd></div>
      <div><dt>Duração</dt><dd>${eventDuration(event)}</dd></div>
      <div><dt>Área</dt><dd>${event.area_id || event.regiao_id || "—"}</dd></div>
      <div><dt>Câmera</dt><dd>${event.camera_id || "—"}</dd></div>
      <div><dt>Regra acionada</dt><dd>${event.regra_id || event.rule_id || "—"}</dd></div>
      <div><dt>Severidade</dt><dd>${eventSeverity(event)}</dd></div>
      <div><dt>Responsável</dt><dd>${event.responsavel || "—"}</dd></div>
      <div><dt>Status</dt><dd>${eventStatusLabel(event.status)}</dd></div>
      <div><dt>Entregas de alerta</dt><dd>${event.alert_sent || event.alerta_enviado ? "Registradas" : "—"}</dd></div>
    </dl>
    <h3>Timeline</h3>
    ${renderTimelineList(eventTimelineSteps(event))}
    <h3>Metadados</h3>
    <pre>${JSON.stringify(event.metadados || event.metadata || {}, null, 2)}</pre>
    <div class="cx-detail-actions">
      <button type="button" ${event.id ? `data-event-detail-action="acknowledged" data-event-id="${event.id}"` : "disabled"}>Reconhecer</button>
      <button type="button" disabled title="Encerramento manual será ativado quando o backend suportar esta ação.">Encerrar</button>
      <button type="button" disabled title="Descarte manual será ativado quando o backend suportar esta ação.">Descartar falso positivo</button>
    </div>
  `;
}

function evidenceDetail(event) {
  return `
    <h2>Evidência · ${eventTitle(event)}</h2>
    <div class="cx-detail-frame">${event.midia_path || event.snapshot_path ? `<img src="/eventos/${event.id}/evidence" alt="Evidência visual" />` : "Sem imagem disponível"}</div>
    <dl>
      <div><dt>Evento</dt><dd>${eventTitle(event)}</dd></div>
      <div><dt>Horário</dt><dd>${eventStart(event)}</dd></div>
      <div><dt>Área</dt><dd>${event.area_id || "—"}</dd></div>
      <div><dt>Câmera</dt><dd>${event.camera_id || "—"}</dd></div>
      <div><dt>Retenção</dt><dd>${event.retention || "Política local"}</dd></div>
      <div><dt>Link seguro</dt><dd>${event.midia_path || event.snapshot_path ? "Disponível pela API local" : "—"}</dd></div>
    </dl>
    <h3>Timeline</h3>
    ${renderTimelineList(eventTimelineSteps(event))}
    <h3>Metadados</h3>
    <pre>${JSON.stringify(event.metadados || event.metadata || {}, null, 2)}</pre>
  `;
}

function alertDeliveryDetail(delivery) {
  return `
    <h2>Entrega de alerta</h2>
    <dl>
      <div><dt>Evento</dt><dd>${delivery.evento_id || "Teste"}</dd></div>
      <div><dt>Destinatário</dt><dd>${delivery.destinatario || delivery.recipient_id || "—"}</dd></div>
      <div><dt>Canal</dt><dd>${delivery.channel || delivery.canal || "e-mail"}</dd></div>
      <div><dt>Horário</dt><dd>${delivery.sent_at || delivery.last_attempt_at || delivery.criado_em || "—"}</dd></div>
      <div><dt>Tentativas</dt><dd>${delivery.attempts || delivery.tentativas || 1}</dd></div>
      <div><dt>Status</dt><dd>${alertStatusLabel(delivery.status)}</dd></div>
      <div><dt>Erro</dt><dd>${delivery.erro || delivery.error || "—"}</dd></div>
    </dl>
  `;
}

function humanCondition(rule) {
  const type = rule.condicao?.type || rule.tipo_evento;
  const labels = {
    presence_in_zone: "Presença em zona",
    absence_in_zone: "Ausência em zona",
    count_between: "Contagem mínima/máxima",
    machine_state: "Estado da máquina",
    camera_status: "Câmera indisponível",
    no_motion_in_region: "Ausência de movimento",
    active_without_operator: "Máquina ativa sem operador",
    restricted_area_occupied: "Pessoa em área restrita",
  };
  return labels[type] || type || "Em desenvolvimento";
}

function reportLabel(key) {
  const labels = {
    eventos: "Eventos por período",
    cameras: "Disponibilidade das câmeras",
    tempo_maquina_ativa: "Tempo ativo",
    tempo_maquina_parada: "Tempo parado",
    quantidade_paradas: "Paradas",
    alertas: "Alertas",
    evidencias: "Evidências",
  };
  return labels[key] || key.replaceAll("_", " ");
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
    <ol class="cx-rule-steps">
      <li>Escolher câmera</li>
      <li>Escolher área ou zona</li>
      <li>Escolher condição</li>
      <li>Definir duração mínima</li>
      <li>Definir severidade</li>
      <li>Configurar alertas</li>
      <li>Revisar</li>
      <li>Ativar</li>
    </ol>
    <form id="visualRuleForm" class="form">
      <label>Nome da regra<input name="nome" required placeholder="Ex.: Máquina ativa sem operador" /></label>
      <label>Câmera<input name="camera_id" required placeholder="ID da câmera cadastrada" /></label>
      <label>Área ou zona<input name="regiao_id" placeholder="Ex.: operador, doca_1, zona_segurança" /></label>
      <label>Tipo do evento<input name="tipo_evento" required value="active_without_operator" /></label>
      <label>Condição
        <select name="condition_type">
          <option value="all">Máquina ativa + ausência em zona</option>
          <option value="presence_in_zone">Presença em zona</option>
          <option value="absence_in_zone">Ausência em zona</option>
          <option value="dwell_time">Permanência acima do limite</option>
          <option value="count_between">Contagem mínima e máxima</option>
          <option value="machine_state">Estado da máquina</option>
          <option value="camera_status">Status da câmera</option>
          <option value="no_motion_in_region">Ausência de movimento</option>
          <option disabled>Circulação em área configurada — em desenvolvimento</option>
          <option disabled>Proximidade — em desenvolvimento</option>
        </select>
      </label>
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
      <div class="cx-rule-human-summary">
        Quando a condição configurada permanecer pelo tempo mínimo, a Campex cria um evento único, registra evidência quando disponível e avisa os responsáveis selecionados.
      </div>
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
  if (type === "dwell_time") return { type: "presence_in_zone", zone_id: zone, min_count: 1 };
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
  if (["aberto", "em análise", "reconhecido", "encerrado", "descartado"].includes(currentTab)) return eventStatusLabel(row.status).toLowerCase() === currentTab;
  if (currentTab === "paradas") return text.includes("stoppage") || text.includes("parada");
  if (currentTab === "pessoas") return text.includes("restricted") || text.includes("pessoa");
  if (currentTab === "máquinas") return text.includes("machine") || text.includes("máquina");
  if (currentTab === "com evidência") return Boolean(row.midia_path || row.snapshot_path);
  if (currentTab === "regras de alerta") return row.workspace_kind === "regra";
  if (currentTab === "destinatários") return row.workspace_kind === "destinatario";
  if (currentTab === "entregas") return row.workspace_kind === "entrega";
  if (currentTab === "falhas") return row.workspace_kind === "entrega" && String(row.status).toLowerCase() === "failed";
  if (currentTab === "pendentes") return text.includes("pending") || text.includes("failed");
  if (currentTab === "enviados") return text.includes("sent");
  if (currentTab === "ativas") return row.ativo === true || row.ativo === 1;
  if (currentTab === "inativas") return row.ativo === false || row.ativo === 0;
  if (currentTab === "em desenvolvimento") return humanCondition(row) === "Em desenvolvimento";
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
    const payload = config.load ? await config.load() : await requestJson(config.endpoint);
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
  const eventDetailAction = event.target.closest("[data-event-detail-action]");
  if (eventDetailAction) {
    eventDetailAction.textContent = "Salvando...";
    try {
      await requestJson(`/eventos/${eventDetailAction.dataset.eventId}`, {
        method: "PATCH",
        body: JSON.stringify({ status: eventDetailAction.dataset.eventDetailAction }),
      });
      eventDetailAction.textContent = "Atualizado";
      await loadPage(window.location.pathname);
      closeSidePanels();
      closeDrawer();
    } catch (error) {
      eventDetailAction.textContent = "Erro";
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
