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
let operationsSelectedPeriod = "day";

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
  "/operations-view": {
    title: "Operations",
    section: "operation",
    breadcrumb: "Operação / Operations",
    permissions: [],
    heading: "Operations",
    subtitle: "O que merece atenção na operação.",
    action: "Atualizar",
    tabs: ["Hoje", "Turno", "Semana", "Mês", "Personalizado"],
    filters: ["Período", "Família", "Ativo"],
    columns: ["Item", "Família", "Duração", "Eventos", "Rastreabilidade"],
    customRender: renderOperationsReadModelPage,
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
    title: "Events",
    section: "operation",
    breadcrumb: "Operations / Events",
    permissions: [],
    heading: "Events",
    subtitle: "Memória operacional verificável: o que aconteceu, quando, onde e como foi tratado.",
    endpoint: "/eventos",
    action: "Atualizar",
    emptyTitle: "Nenhum evento operacional registrado neste período.",
    emptyDescription: "Os acontecimentos monitorados pela Campex aparecerão aqui.",
    tabs: ["Todos", "Abertos", "Encerrados", "Novo", "Reconhecido", "Resolvido", "Não classificados", "Com evidência"],
    filters: ["Período", "Unidade", "Área", "Processo", "Ativo", "Família", "Estado físico", "Workflow"],
    columns: ["Evento", "Contexto", "Horário", "Duração", "Workflow", "Evidência", "Ação"],
    row: eventRow,
    card: eventCard,
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
    title: "Intelligence",
    section: "intelligence",
    breadcrumb: "Intelligence",
    permissions: [],
    heading: "Intelligence",
    subtitle: "O que a Campex entendeu sobre a operação que merece ser percebido.",
    endpoint: "/operations/read-model/insights",
    action: "Atualizar",
    emptyTitle: "Ainda não existem dados suficientes para gerar padrões confiáveis.",
    emptyDescription: "A Campex só apresenta insights quando os eventos classificados sustentam a constatação.",
    tabs: ["Briefing", "Atenção", "Padrões", "KPIs", "Causas"],
    filters: [],
    columns: ["Insight", "Número", "Por que", "Eventos", "Investigar"],
    customRender: renderIntelligencePage,
    row: (item) => [item.statement, item.number || "—", item.why || "—", traceButton("Eventos", item.event_uuids), `<a class="cx-link" href="/events">Investigar</a>`],
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

function secondsLabel(value) {
  const total = Math.max(0, Math.round(Number(value || 0)));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours) return `${hours}h ${String(minutes).padStart(2, "0")}m`;
  if (minutes) return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
  return `${seconds}s`;
}

function familyLabel(family) {
  const labels = {
    interruption: "Interrupções",
    wait: "Esperas",
    absence: "Ausências",
    flow: "Fluxo/movimentação",
    unknown: "Sem classificação",
  };
  return labels[family] || family || "Sem classificação";
}

function isOfficialFamily(family) {
  return ["interruption", "wait", "absence", "flow"].includes(String(family || ""));
}

function officialFamilyRows(summary) {
  return (summary.events_by_family || []).filter((item) => isOfficialFamily(item.key));
}

function officialEventCount(summary) {
  return officialFamilyRows(summary).reduce((sum, item) => sum + Number(item.total_events || 0), 0);
}

function officialDuration(summary) {
  return officialFamilyRows(summary).reduce((sum, item) => sum + Number(item.total_duration_seconds || 0), 0);
}

function unknownEventCount(summary, currentPayload) {
  const summaryUnknown = (summary.events_by_family || [])
    .filter((item) => !isOfficialFamily(item.key))
    .reduce((sum, item) => sum + Number(item.total_events || 0), 0);
  const openUnknown = (currentPayload.open_events || []).filter((event) => !isOfficialFamily(event.event_family)).length;
  return Math.max(summaryUnknown, openUnknown);
}

function classifiedOpenEvents(currentPayload) {
  return (currentPayload.open_events || []).filter((event) => isOfficialFamily(event.event_family));
}

function formatDateParts(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  const day = date.toLocaleDateString("pt-BR", { day: "2-digit", month: "short" }).replace(".", "");
  const time = date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  return { day, time };
}

function formatOperationsPeriod(period) {
  const start = formatDateParts(period?.start);
  const end = formatDateParts(period?.end);
  if (!start || !end) return "Período não informado";
  if (start.day === end.day) return `Hoje · ${start.day}<br><span>${start.time} → ${end.time}</span>`;
  return `${start.day} → ${end.day}<br><span>${start.time} → ${end.time}</span>`;
}

function operationPeriod() {
  const selected = document.querySelector("#operationsPeriod")?.value;
  const tabPeriod = { hoje: "day", turno: "turno", semana: "week", mês: "month", personalizado: "custom" }[currentTab];
  return selected || operationsSelectedPeriod || tabPeriod || "day";
}

function readModelQuery(extra = {}) {
  const params = new URLSearchParams();
  params.set("period", operationPeriod());
  Object.entries(extra).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") params.set(key, value);
  });
  return params.toString();
}

function groupByKey(items = []) {
  return new Map((items || []).map((item) => [item.key, item]));
}

function getFamily(summary, family) {
  return groupByKey(summary.events_by_family || []).get(family) || {
    key: family,
    total_events: 0,
    total_duration_seconds: 0,
    event_uuids: [],
  };
}

function comparisonFor(comparison, key) {
  return comparison?.metrics?.[key] || { current: 0, previous: 0, absolute_difference: 0, percent_change: null };
}

function comparisonText(metric) {
  if (metric.percent_change === null || metric.percent_change === undefined) return "sem base anterior";
  const sign = metric.percent_change > 0 ? "+" : "";
  return `${sign}${metric.percent_change}% vs período anterior`;
}

function coverageWarning(coverage) {
  if (!coverage || coverage.status === "observed") return "";
  const label = coverage.status === "partial" ? "Cobertura parcial" : "Cobertura desconhecida";
  const detail = coverage.reason || "Alguns períodos não possuem dados suficientes.";
  return `<div class="cx-ops-warning"><strong>${label}</strong><span>${detail}</span></div>`;
}

function traceButton(label, uuids = []) {
  const list = (uuids || []).filter(Boolean).join(",");
  if (!list) return `<button type="button" class="cx-linklike" disabled>${label}</button>`;
  return `<button type="button" class="cx-linklike" data-event-uuids="${list}">${label}</button>`;
}

function operationsBriefing(summary, lossesPayload) {
  const coverage = summary.coverage || {};
  const classifiedCount = officialEventCount(summary);
  if (!classifiedCount) {
    if (Number(summary.total_events || 0) > 0) {
      return "Sem eventos operacionais classificados suficientes neste período.";
    }
    return coverage.status && coverage.status !== "observed"
      ? "Ainda não há eventos no período, e a cobertura dos dados não permite afirmar que a operação esteve sem ocorrências."
      : "Nenhum evento operacional foi registrado no período selecionado.";
  }
  const topArea = (summary.events_by_area || []).find((item) => item.key !== "não informado");
  const topAsset = (lossesPayload.by_asset || []).find((item) => item.key !== "não informado");
  const topFamily = officialFamilyRows(summary)[0];
  if (topArea && topAsset && topFamily) {
    return `${topArea.key} concentrou ${secondsLabel(topArea.total_duration_seconds)} em ${familyLabel(topFamily.key).toLowerCase()}. O ativo ${topAsset.key} é o principal ponto de atenção no período.`;
  }
  if (topFamily) {
    return `${familyLabel(topFamily.key)} concentraram ${secondsLabel(topFamily.total_duration_seconds)} no período selecionado.`;
  }
  return "A Campex consolidou os eventos do período, mas ainda não há concentração operacional suficiente para destacar uma área.";
}

function operationsAttention(summary, lossesPayload, comparisonPayload, currentPayload) {
  const callouts = [];
  const topAsset = (lossesPayload.by_asset || [])[0];
  const totalLossDuration = (lossesPayload.by_family || []).reduce((sum, item) => sum + Number(item.total_duration_seconds || 0), 0);
  if (topAsset && totalLossDuration > 0) {
    const share = Math.round((Number(topAsset.total_duration_seconds || 0) / totalLossDuration) * 100);
    callouts.push({
      title: `${topAsset.key} concentrou ${share}% das perdas monitoradas.`,
      why: `${secondsLabel(topAsset.total_duration_seconds)} em ${topAsset.total_events} evento(s) classificados como perda operacional.`,
      event_uuids: topAsset.event_uuids,
    });
  }
  const durationComparison = comparisonFor(comparisonPayload, "total_duration_seconds");
  if (durationComparison.percent_change !== null && Math.abs(durationComparison.percent_change) >= 10) {
    callouts.push({
      title: `A duração total mudou ${comparisonText(durationComparison)}.`,
      why: `${secondsLabel(durationComparison.current)} no período atual contra ${secondsLabel(durationComparison.previous)} no período anterior.`,
      event_uuids: comparisonPayload.current_event_uuids || [],
    });
  }
  const repeatedAsset = (summary.events_by_asset || []).find((item) => item.total_events >= 3 && item.key !== "não informado");
  if (repeatedAsset) {
    callouts.push({
      title: `${repeatedAsset.total_events} ocorrências foram registradas no mesmo ativo.`,
      why: `O ativo ${repeatedAsset.key} repetiu eventos no período selecionado.`,
      event_uuids: repeatedAsset.event_uuids,
    });
  }
  const openClassified = classifiedOpenEvents(currentPayload);
  if (openClassified.length) {
    callouts.push({
      title: `${openClassified.length} evento(s) operacionais continuam abertos.`,
      why: "Há ocorrências físicas em andamento que ainda não foram normalizadas.",
      event_uuids: openClassified.map((event) => event.event_uuid),
    });
  }
  return callouts.slice(0, 4);
}

function renderOperationsCards(summary, currentPayload, comparisonPayload) {
  const families = ["interruption", "wait", "absence", "flow"];
  return families.map((family) => {
    const item = getFamily(summary, family);
    const hasData = item.total_events > 0;
    return `
      <article class="cx-ops-card">
        <span>${familyLabel(family)}</span>
        <strong>${hasData ? secondsLabel(item.total_duration_seconds) : "Sem dados"}</strong>
        <small>${hasData ? `${item.total_events} evento(s)` : "Aguardando eventos reais"}</small>
        ${traceButton("Ver eventos", item.event_uuids)}
      </article>
    `;
  }).join("") + `
    <article class="cx-ops-card cx-ops-card-open">
      <span>Eventos abertos</span>
      <strong>${classifiedOpenEvents(currentPayload).length || 0}</strong>
      <small>Ocorrências operacionais classificadas ainda OPEN</small>
      ${traceButton("Ver ativos", classifiedOpenEvents(currentPayload).map((event) => event.event_uuid))}
    </article>
  `;
}

function eventContextLabel(event) {
  const asset = event.asset_name || event.asset_id || event.machine_name || event.machine_monitor_id;
  const process = event.process_name || event.process_id;
  const area = event.area_name || event.area_context_id || event.area_id;
  const camera = event.camera_name || event.camera_id;
  const primary = asset || process || area || camera || "Contexto operacional não informado";
  const path = [area, process].filter(Boolean).join(" → ");
  return { primary, path: path || camera || "Contexto não informado" };
}

function renderOperationsCurrent(currentPayload) {
  const events = classifiedOpenEvents(currentPayload);
  if (!events.length) return `<div class="cx-empty-state"><strong>Nenhum evento operacional classificado aberto.</strong><p>A operação não possui ocorrências OPEN classificadas no momento.</p></div>`;
  return events.map((event) => `
    <article class="cx-ops-current">
      <strong>${eventContextLabel(event).primary}</strong>
      <span>${familyLabel(event.event_family)} há ${secondsLabel(event.current_duration_seconds)}</span>
      <small>${eventContextLabel(event).path} · workflow: ${event.workflow_status || "new"}</small>
      ${traceButton("Ver evento", [event.event_uuid])}
    </article>
  `).join("");
}

function renderOperationsRanking(title, items = [], total = 0) {
  const rows = (items || []).slice(0, 5);
  if (!rows.length) return `<section class="cx-ops-block"><h3>${title}</h3><p class="muted">Sem dados para ranking.</p></section>`;
  return `
    <section class="cx-ops-block">
      <h3>${title}</h3>
      ${rows.map((item) => {
        const share = total ? Math.round((Number(item.total_duration_seconds || 0) / total) * 100) : 0;
        return `<div class="cx-ops-rank"><strong>${item.key}</strong><span>${secondsLabel(item.total_duration_seconds)} · ${item.total_events} evento(s) · ${share}%</span>${traceButton("Eventos", item.event_uuids)}</div>`;
      }).join("")}
    </section>
  `;
}

function renderUnknownQualityNote(summary, currentPayload) {
  const count = unknownEventCount(summary, currentPayload);
  if (!count) return "";
  return `<div class="cx-ops-quality"><strong>${count} evento(s) ainda não possuem classificação operacional.</strong><span>Eles continuam preservados para auditoria, mas não entram nos indicadores oficiais da Operations.</span></div>`;
}

function renderTraceDrawer(uuids) {
  drawer.classList.add("open");
  drawer.setAttribute("aria-hidden", "false");
  drawerContent.innerHTML = `
    <h2>Eventos que explicam o número</h2>
    <p>Esta métrica foi composta pelos eventos abaixo.</p>
    <ul class="cx-trace-list">${uuids.map((uuid, index) => `<li><a class="cx-link" href="/events?event_uuid=${encodeURIComponent(uuid)}">Abrir evento ${index + 1}</a></li>`).join("")}</ul>
    <p class="muted">Cada item leva ao registro operacional que originou o número.</p>
  `;
  drawer.querySelector("h2")?.setAttribute("id", "workspaceDrawerTitle");
  drawer.focus({ preventScroll: true });
}

async function renderOperationsReadModelPage(config) {
  const params = readModelQuery();
  const [currentPayload, summary, lossesPayload, comparisonPayload] = await Promise.all([
    requestJson(`/operations/read-model/current?${params}`),
    requestJson(`/operations/read-model/summary?${params}`),
    requestJson(`/operations/read-model/losses?${params}`),
    requestJson(`/operations/read-model/comparison?${params}`),
  ]);
  rowsCache = [
    ...officialFamilyRows(summary).map((item) => ({ ...item, kind: "family" })),
    ...(lossesPayload.by_asset || []).map((item) => ({ ...item, kind: "asset" })),
  ];
  const totalLossDuration = (lossesPayload.by_family || []).reduce((sum, item) => sum + Number(item.total_duration_seconds || 0), 0);
  const callouts = operationsAttention(summary, lossesPayload, comparisonPayload, currentPayload);
  const hasOperationalData = officialEventCount(summary) > 0 || classifiedOpenEvents(currentPayload).length > 0;
  title.textContent = "";
  heading.textContent = "Como está sua operação?";
  subtitle.textContent = "";
  tableTitle.textContent = "Rastreabilidade operacional";
  tableHint.textContent = "Cada número pode ser explicado pelos eventos que o formaram.";
  primaryAction.textContent = "Atualizar";
  primaryAction.onclick = () => loadPage(window.location.pathname);
  filters.innerHTML = `
    <label>Período
      <select id="operationsPeriod">
        <option value="day" ${operationPeriod() === "day" ? "selected" : ""}>Hoje</option>
        <option value="turno" ${operationPeriod() === "turno" ? "selected" : ""}>Turno</option>
        <option value="week" ${operationPeriod() === "week" ? "selected" : ""}>Semana</option>
        <option value="month" ${operationPeriod() === "month" ? "selected" : ""}>Mês</option>
      </select>
    </label>
  `;
  const operationalHeader = `
    <section class="cx-ops-header">
      <div>
        <small>Unidade</small>
        <strong>${summary.filters?.site_id || "Todas as unidades"}</strong>
      </div>
      <div>
        <small>Período</small>
        <strong>${formatOperationsPeriod(summary.period)}</strong>
      </div>
      <div>
        <small>Cobertura</small>
        <strong>${summary.coverage?.status || "unknown"}</strong>
      </div>
      <div>
        <small>Última atualização</small>
        <strong>${new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}</strong>
      </div>
    </section>
  `;
  cards.innerHTML = `
    <section class="cx-ops-page">
      <div class="cx-ops-title">
        <span>Operations</span>
        <h2>Como está sua operação?</h2>
      </div>
      ${operationalHeader}
      ${coverageWarning(summary.coverage)}
      ${renderUnknownQualityNote(summary, currentPayload)}
      <section class="cx-ops-briefing">
        <small>Briefing operacional</small>
        <strong>${hasOperationalData ? operationsBriefing(summary, lossesPayload) : "Sem dados operacionais suficientes neste período."}</strong>
      </section>
      <section class="cx-ops-grid">${renderOperationsCards(summary, currentPayload, comparisonPayload)}</section>
      ${hasOperationalData ? `
        <section class="cx-ops-layout">
          <div class="cx-ops-column">
            <section class="cx-ops-block"><h3>O que merece atenção</h3>${callouts.length ? callouts.map((item) => `<article class="cx-ops-callout"><strong>${item.title}</strong><p>${item.why}</p>${traceButton("Eventos relacionados", item.event_uuids)}</article>`).join("") : '<p class="muted">Sem destaque operacional sustentado pelos dados do período.</p>'}</section>
            <section class="cx-ops-block"><h3>Principais perdas</h3>${renderOperationsRanking("Por ativo", lossesPayload.by_asset, totalLossDuration)}${renderOperationsRanking("Por processo", lossesPayload.by_process, totalLossDuration)}${renderOperationsRanking("Por área", lossesPayload.by_area, totalLossDuration)}</section>
          </div>
          <aside class="cx-ops-column">
            <section class="cx-ops-block"><h3>Operação agora</h3>${renderOperationsCurrent(currentPayload)}</section>
            <section class="cx-ops-block"><h3>Comparação</h3><p>Eventos: ${comparisonText(comparisonFor(comparisonPayload, "total_events"))}</p><p>Duração: ${comparisonText(comparisonFor(comparisonPayload, "total_duration_seconds"))}</p></section>
          </aside>
        </section>
      ` : `
        <section class="cx-ops-empty">
          <strong>Sem eventos operacionais classificados suficientes neste período.</strong>
          <p>A Campex ainda está aguardando eventos válidos de interrupção, espera, ausência ou fluxo para montar atenção, perdas e comparação.</p>
        </section>
      `}
    </section>
  `;
  renderTabs(config);
  head.innerHTML = `<tr>${config.columns.map((column) => `<th>${column}</th>`).join("")}</tr>`;
  const rows = rowsCache;
  body.innerHTML = rows.length ? rows.map((item) => `
    <tr>
      <td>${item.key}</td>
      <td>${item.kind === "family" ? familyLabel(item.key) : "Ativo"}</td>
      <td>${secondsLabel(item.total_duration_seconds)}</td>
      <td>${item.total_events}</td>
      <td>${traceButton("Ver eventos", item.event_uuids)}</td>
    </tr>
  `).join("") : `<tr><td colspan="${config.columns.length}">${emptyState({ ...config, emptyTitle: "Sem eventos no período.", emptyDescription: "A Campex ainda não registrou eventos operacionais para esta seleção." })}</td></tr>`;
  grid.style.display = "none";
  document.querySelector(".cx-panel")?.classList.toggle("cx-ops-hide-panel", !rows.length);
}

function intelligenceBriefingText(payload) {
  const lines = payload.briefing || [];
  if (!lines.length) return "Ainda não existem eventos operacionais classificados suficientes neste período.";
  return lines.join(" ");
}

function intelligenceKpiValue(kpi) {
  if (kpi.value_seconds !== undefined && kpi.value_seconds !== null) return secondsLabel(kpi.value_seconds);
  if (kpi.value !== undefined && kpi.value !== null) return String(kpi.value);
  return "Sem dados";
}

function renderInsightCard(item) {
  return `
    <article class="cx-intel-card">
      <div>
        <strong>${item.statement}</strong>
        <span>${item.number || "—"}</span>
      </div>
      <p><b>Por que a Campex está destacando isso?</b> ${item.why || "Insight gerado por regra determinística a partir dos eventos do período."}</p>
      ${traceButton("Investigar", item.event_uuids)}
    </article>
  `;
}

function renderInsightList(items, emptyText) {
  if (!items?.length) return `<div class="cx-empty-state"><strong>${emptyText}</strong><p>A Campex não inventa padrões quando os dados não sustentam a afirmação.</p></div>`;
  return `<div class="cx-intel-list">${items.map(renderInsightCard).join("")}</div>`;
}

function renderCauseRows(causes = []) {
  if (!causes.length) return `<p class="muted">Nenhuma causa confirmada foi registrada por humanos neste período.</p>`;
  return causes.map((cause) => `
    <div class="cx-intel-cause">
      <strong>${cause.key}</strong>
      <span>${secondsLabel(cause.total_duration_seconds)} · ${cause.total_events} evento(s)</span>
      ${traceButton("Eventos", cause.event_uuids)}
    </div>
  `).join("");
}

async function renderIntelligencePage(config) {
  const params = readModelQuery();
  const payload = await requestJson(`/operations/read-model/insights?${params}`);
  const allInsights = [...(payload.attention || []), ...(payload.patterns || [])];
  rowsCache = allInsights;
  title.textContent = "Intelligence";
  heading.textContent = "O que a Campex entendeu sobre a operação?";
  subtitle.textContent = "Insights determinísticos gerados a partir dos eventos operacionais do período.";
  tableTitle.textContent = "Rastreabilidade dos insights";
  tableHint.textContent = "Cada insight pode ser rastreado até os eventos que o originaram.";
  primaryAction.textContent = "Atualizar";
  primaryAction.onclick = () => loadPage(window.location.pathname);
  filters.innerHTML = `
    <label>Período
      <select id="operationsPeriod">
        <option value="day" ${operationPeriod() === "day" ? "selected" : ""}>Hoje</option>
        <option value="turno" ${operationPeriod() === "turno" ? "selected" : ""}>Turno</option>
        <option value="week" ${operationPeriod() === "week" ? "selected" : ""}>Semana</option>
        <option value="month" ${operationPeriod() === "month" ? "selected" : ""}>Mês</option>
      </select>
    </label>
  `;
  const unknownCount = Number(payload.data_quality?.unknown_events || 0);
  cards.innerHTML = `
    <section class="cx-intel-page">
      <section class="cx-ops-header">
        <div>
          <small>Período</small>
          <strong>${formatOperationsPeriod(payload.period)}</strong>
        </div>
        <div>
          <small>Cobertura</small>
          <strong>${payload.coverage?.status || "unknown"}</strong>
        </div>
        <div>
          <small>Eventos classificados</small>
          <strong>${payload.data_quality?.classified_events || 0}</strong>
        </div>
        <div>
          <small>Última atualização</small>
          <strong>${new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}</strong>
        </div>
      </section>
      ${coverageWarning(payload.coverage)}
      ${unknownCount ? `<div class="cx-ops-quality"><strong>${unknownCount} evento(s) sem classificação operacional.</strong><span>Preservados para auditoria, fora dos insights oficiais.</span></div>` : ""}
      <section class="cx-intel-briefing">
        <small>Briefing do período</small>
        <strong>${intelligenceBriefingText(payload)}</strong>
      </section>
      <section class="cx-intel-kpis">
        ${(payload.kpis || []).map((kpi) => `
          <article>
            <button type="button" aria-label="Marcar ${kpi.label} como KPI da operação">☆</button>
            <span>${kpi.label}</span>
            <strong>${intelligenceKpiValue(kpi)}</strong>
            ${traceButton("Eventos", kpi.event_uuids)}
          </article>
        `).join("")}
      </section>
      <section class="cx-intel-layout">
        <div class="cx-intel-column">
          <section class="cx-ops-block">
            <h3>O que merece atenção</h3>
            ${renderInsightList(payload.attention, "Sem destaques sustentados pelos dados do período.")}
          </section>
          <section class="cx-ops-block">
            <h3>Padrões verificáveis</h3>
            ${renderInsightList(payload.patterns, "Ainda não há padrões matematicamente verificáveis.")}
          </section>
        </div>
        <aside class="cx-intel-column">
          <section class="cx-ops-block">
            <h3>Causas confirmadas</h3>
            <p class="muted">Somente informações registradas por pessoas entram aqui. Observações da câmera não viram causa automaticamente.</p>
            ${renderCauseRows(payload.confirmed_causes)}
          </section>
          <section class="cx-ops-block">
            <h3>Comparação</h3>
            <p>Eventos: ${comparisonText(payload.comparison?.metrics?.total_events || {})}</p>
            <p>Duração: ${comparisonText(payload.comparison?.metrics?.total_duration_seconds || {})}</p>
          </section>
        </aside>
      </section>
    </section>
  `;
  renderTabs(config);
  head.innerHTML = `<tr>${config.columns.map((column) => `<th>${column}</th>`).join("")}</tr>`;
  body.innerHTML = rowsCache.length ? rowsCache.map((item) => `
    <tr>
      <td>${item.statement}</td>
      <td>${item.number || "—"}</td>
      <td>${item.why || "—"}</td>
      <td>${traceButton("Eventos", item.event_uuids)}</td>
      <td><a class="cx-link" href="/events">Investigar</a></td>
    </tr>
  `).join("") : `<tr><td colspan="${config.columns.length}">${emptyState(config)}</td></tr>`;
  grid.style.display = "none";
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
  if (status === "closed") return "Encerrado";
  return status || "Aberto";
}

function workflowLabel(status) {
  if (status === "acknowledged") return "Reconhecido";
  if (status === "resolved") return "Resolvido";
  return "Novo";
}

function eventSeverity(event) {
  const severity = String(event.severidade || event.severity || "").toLowerCase();
  if (severity) return severity;
  const text = `${event.tipo || ""} ${event.event_type || ""} ${event.new_state || ""}`.toLowerCase();
  if (text.includes("offline") || text.includes("parada") || text.includes("stoppage")) return "alta";
  if (text.includes("restricted") || text.includes("sem_operador")) return "média";
  return "normal";
}

function eventFamily(event) {
  return event.event_family || event.business_taxonomy?.event_family || "unknown";
}

function eventSubtype(event) {
  return event.event_subtype || event.business_taxonomy?.event_subtype || event.tipo || event.technical_type || "evento";
}

function eventFamilyTitle(event) {
  const subtype = eventSubtype(event);
  if (subtype === "machine_stoppage") return "Parada operacional";
  if (subtype === "machine_running_without_operator") return "Máquina ativa sem operador";
  if (subtype === "machine_stopped_with_operator") return "Máquina parada com operador";
  if (subtype === "workstation_unattended") return "Posto sem operador";
  if (eventFamily(event) === "interruption") return "Interrupção operacional";
  if (eventFamily(event) === "wait") return "Espera operacional";
  if (eventFamily(event) === "absence") return "Ausência operacional";
  if (eventFamily(event) === "flow") return "Fluxo operacional";
  return "Evento não classificado";
}

function eventWorkflow(event) {
  return event.workflow_status || "new";
}

function eventPhysicalStatus(event) {
  return event.physical_status || event.status || "open";
}

function eventStart(event) {
  return event.inicio || event.started_at || event.criado_em || "—";
}

function eventEnd(event) {
  return event.fim || event.ended_at || "";
}

function eventDuration(event) {
  const value = event.duracao ?? event.duration_seconds ?? event.read_duration_seconds;
  return value === null || value === undefined || value === "" ? "—" : secondsLabel(value);
}

function eventTitle(event) {
  return eventFamilyTitle(event);
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
  return event.midia_path || event.snapshot_path ? `<a class="cx-link" href="/eventos/${event.id}/evidence" target="_blank">Evidência</a>` : "Sem evidência";
}

function rowMenu() {
  return '<button class="cx-row-menu" type="button" data-open-detail>•••</button>';
}

function eventContext(event) {
  const physical = event.physical_context || {};
  const asset = event.asset_name || event.asset_id || physical.asset_id || event.machine_name || event.machine_monitor_id || physical.machine_monitor_id;
  const process = event.process_name || event.process_id || physical.process_id;
  const area = event.area_name || event.area_context_id || physical.area_context_id || event.area_id || physical.area_id;
  const camera = event.camera_name || event.camera_id || physical.camera_id;
  const unit = event.unidade_id || event.unit_id || physical.unidade_id || physical.site_id;
  const primary = asset || process || area || camera || "Contexto não informado";
  const location = [area, process].filter(Boolean).join(" → ") || unit || camera || "Local não informado";
  return { primary, location, asset, process, area, camera, unit };
}

function eventTimeRange(event) {
  const start = eventStart(event);
  const end = eventEnd(event);
  if (!end || end === "—") return `${start} → em andamento`;
  return `${start} → ${end}`;
}

function eventObservedSummary(event) {
  const observed = event.observed_context || event.metadata || event.metadados || {};
  const parts = [];
  if (observed.operator_absent_seconds) parts.push(`Operador ausente durante ${secondsLabel(observed.operator_absent_seconds)}`);
  if (observed.operator_present_seconds) parts.push(`Operador presente durante ${secondsLabel(observed.operator_present_seconds)}`);
  if (observed.duracao || event.duracao) parts.push(`Duração observada: ${eventDuration(event)}`);
  if (event.confianca || observed.confianca) parts.push(`Confiança: ${Number(event.confianca || observed.confianca).toFixed(2)}`);
  return parts.join(" · ") || "Fatos observados disponíveis no detalhe.";
}

function filterCanonicalEvents(rows) {
  return (rows || []).filter((event) => {
    const family = eventFamily(event);
    return family !== "unknown" || currentTab === "não classificados";
  });
}

function eventRow(event) {
  const context = eventContext(event);
  return [
    `<div class="cx-event-cell"><strong>${eventTitle(event)}</strong><span>${familyLabel(eventFamily(event))}</span></div>`,
    `<div class="cx-event-cell"><strong>${context.primary}</strong><span>${context.location}</span></div>`,
    eventTimeRange(event),
    eventPhysicalStatus(event) === "open" ? "em andamento" : eventDuration(event),
    badge(workflowLabel(eventWorkflow(event))),
    evidenceLink(event),
    rowMenu(),
  ];
}

function eventCard(event) {
  const context = eventContext(event);
  const physical = eventPhysicalStatus(event);
  return `
    <article class="cx-event-card" data-event-card="${event.id || ""}">
      <div class="cx-event-card-head">
        <div>
          <strong>${eventTitle(event)}</strong>
          <span>${context.primary} · ${context.location}</span>
        </div>
        ${badge(physical === "open" ? "Em andamento" : "Encerrado")}
      </div>
      <p>${eventTimeRange(event)} · ${physical === "open" ? "em andamento" : eventDuration(event)}</p>
      <p>${eventObservedSummary(event)}</p>
      <div class="cx-event-card-actions">
        ${badge(workflowLabel(eventWorkflow(event)))}
        ${event.midia_path || event.snapshot_path ? `<a class="cx-link" href="/eventos/${event.id}/evidence" target="_blank">Evidência</a>` : `<span class="muted">Sem evidência</span>`}
        <button class="cx-linklike" type="button" data-open-detail>Abrir evento</button>
      </div>
    </article>
  `;
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
  const workflow = eventWorkflow(event);
  return [
    eventStart(event) !== "—" ? ["Situação iniciada", eventStart(event)] : null,
    event.confirmed_at ? ["Condição confirmada", event.confirmed_at] : null,
    event.id ? ["Evento criado", event.criado_em || eventStart(event)] : null,
    event.midia_path || event.snapshot_path ? ["Evidência salva", "Disponível"] : null,
    event.alert_sent || event.alerta_enviado ? ["Alerta enviado", "Registrado"] : null,
    workflow === "acknowledged" || workflow === "resolved" ? ["Reconhecido", event.acknowledged_at || event.human_context?.acknowledged_at || "—"] : null,
    eventEnd(event) ? ["Normalizado", eventEnd(event)] : null,
    eventPhysicalStatus(event) === "closed" ? ["Encerrado fisicamente", eventEnd(event) || "—"] : null,
    workflow === "resolved" ? ["Resolvido pela gestão", event.resolved_at || event.human_context?.resolved_at || "—"] : null,
  ].filter(Boolean);
}

function renderTimelineList(steps) {
  if (!steps.length) return "<p>Sem etapas registradas.</p>";
  return `<ol class="cx-event-timeline">${steps.map(([label, value]) => `<li><strong>${label}</strong><span>${value}</span></li>`).join("")}</ol>`;
}

function eventDetail(event) {
  const context = eventContext(event);
  const physical = event.physical_context || {};
  const observed = event.observed_context || {};
  const human = event.human_context || {};
  const workflow = eventWorkflow(event);
  const evidence = event.midia_path || event.snapshot_path;
  return `
    <h2>${eventTitle(event)}</h2>
    <p class="muted">${context.primary} · ${context.location}</p>
    <dl>
      <div><dt>Família</dt><dd>${familyLabel(eventFamily(event))}</dd></div>
      <div><dt>Horário</dt><dd>${eventTimeRange(event)}</dd></div>
      <div><dt>Duração</dt><dd>${eventPhysicalStatus(event) === "open" ? "em andamento" : eventDuration(event)}</dd></div>
      <div><dt>Status físico</dt><dd>${eventStatusLabel(eventPhysicalStatus(event))}</dd></div>
      <div><dt>Workflow</dt><dd>${workflowLabel(workflow)}</dd></div>
      <div><dt>Severidade</dt><dd>${eventSeverity(event)}</dd></div>
      <div><dt>Identificador do evento</dt><dd>${event.event_uuid ? "Disponível" : "—"}</dd></div>
    </dl>
    <h3>Evidência</h3>
    <div class="cx-detail-frame">${evidence ? `<img src="/eventos/${event.id}/evidence" alt="Frame da ocorrência" />` : "Este evento não possui evidência visual disponível."}</div>
    <h3>O que a Campex observou</h3>
    <dl>
      <div><dt>Tipo técnico</dt><dd>${event.technical_type || event.tipo || "—"}</dd></div>
      <div><dt>Operador presente</dt><dd>${observed.operador_presente ?? event.operador_presente ?? "—"}</dd></div>
      <div><dt>Confiança</dt><dd>${observed.confianca ?? event.confianca ?? "—"}</dd></div>
      <div><dt>Pessoas</dt><dd>${observed.quantidade_maxima ?? event.quantidade_maxima ?? event.quantidade_atual ?? "—"}</dd></div>
      <div><dt>Contexto observado</dt><dd>${eventObservedSummary(event)}</dd></div>
    </dl>
    <h3>Contexto da operação</h3>
    <dl>
      <div><dt>Empresa</dt><dd>${event.cliente_id || physical.cliente_id || "—"}</dd></div>
      <div><dt>Unidade</dt><dd>${event.unidade_id || physical.unidade_id || physical.site_id || "—"}</dd></div>
      <div><dt>Área</dt><dd>${context.area || "—"}</dd></div>
      <div><dt>Processo</dt><dd>${context.process || "—"}</dd></div>
      <div><dt>Ativo/posto</dt><dd>${context.asset || "—"}</dd></div>
      <div><dt>Câmera</dt><dd>${context.camera || "—"}</dd></div>
    </dl>
    <h3>Timeline</h3>
    ${renderTimelineList(eventTimelineSteps(event))}
    <h3>Gestão do evento</h3>
    <form class="cx-event-workflow-form" data-event-workflow-form data-event-id="${event.id || ""}" data-workflow="${workflow}">
      <label>Causa confirmada<input name="confirmed_cause" value="${human.confirmed_cause || event.confirmed_cause || ""}" placeholder="Ex.: falta de material" /></label>
      <label>Ação tomada<input name="action_taken" value="${human.action_taken || event.action_taken || ""}" placeholder="Ex.: abastecimento solicitado" /></label>
      <label>Notas<textarea name="human_notes" rows="3" placeholder="Observações da gestão">${human.human_notes || event.human_notes || ""}</textarea></label>
      <div class="cx-detail-actions">
        ${workflow === "new" ? `<button type="button" data-event-workflow-action="acknowledge" data-event-id="${event.id}">Reconhecer</button>` : ""}
        ${workflow !== "resolved" ? `<button type="button" data-event-workflow-action="save-human" data-event-id="${event.id}">Salvar contexto</button><button type="button" data-event-workflow-action="resolve" data-event-id="${event.id}">Resolver</button>` : `<span class="muted">Resolvido por ${human.resolved_by || event.resolved_by || "—"} em ${human.resolved_at || event.resolved_at || "—"}</span>`}
      </div>
      <p class="muted" data-event-workflow-status></p>
    </form>
    <details>
      <summary>Detalhe técnico</summary>
      <pre>${JSON.stringify({ technical_type: event.technical_type || event.tipo, observed_context: observed, human_context: human }, null, 2)}</pre>
    </details>
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
  if ((currentTab === "all" || currentTab === "todas" || currentTab === "todos") && (row.tipo || row.event_family || row.event_uuid)) return eventFamily(row) !== "unknown";
  if (currentTab === "all" || currentTab === "todas" || currentTab === "todos" || currentTab === "grade" || currentTab === "lista") return true;
  if (currentTab === "ativa") return cameraStatusLabel(row.status).toLowerCase() === "ativa";
  if (currentTab === "sem sinal") return cameraStatusLabel(row.status).toLowerCase() === "sem sinal";
  if (currentTab === "em configuração") return cameraStatusLabel(row.status).toLowerCase() === "em configuração";
  if (currentTab === "pausada") return cameraStatusLabel(row.status).toLowerCase() === "pausada";
  if (currentTab === "abertos") return eventPhysicalStatus(row) === "open";
  if (currentTab === "encerrados") return eventPhysicalStatus(row) === "closed";
  if (currentTab === "novo") return eventWorkflow(row) === "new";
  if (currentTab === "reconhecido") return eventWorkflow(row) === "acknowledged";
  if (currentTab === "resolvido") return eventWorkflow(row) === "resolved";
  if (currentTab === "não classificados") return eventFamily(row) === "unknown";
  if (["aberto", "em análise", "encerrado", "descartado"].includes(currentTab)) return eventStatusLabel(row.status).toLowerCase() === currentTab;
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
  if (config.title === "Events") {
    filters.innerHTML = `
      <label>Período inicial<input type="date" data-filter="period_start" /></label>
      <label>Período final<input type="date" data-filter="period_end" /></label>
      <label>Unidade<input placeholder="Unidade" data-filter="unidade" /></label>
      <label>Área<input placeholder="Área" data-filter="area" /></label>
      <label>Processo<input placeholder="Processo" data-filter="processo" /></label>
      <label>Ativo<input placeholder="Ativo" data-filter="ativo" /></label>
      <label>Família
        <select data-filter="familia">
          <option value="">Todas</option>
          <option value="interruption">Interrupção</option>
          <option value="wait">Espera</option>
          <option value="flow">Fluxo</option>
          <option value="absence">Ausência</option>
          <option value="unknown">Não classificados</option>
        </select>
      </label>
      <label>Estado físico
        <select data-filter="estado_fisico">
          <option value="">Todos</option>
          <option value="open">Aberto</option>
          <option value="closed">Encerrado</option>
        </select>
      </label>
      <label>Workflow
        <select data-filter="workflow">
          <option value="">Todos</option>
          <option value="new">Novo</option>
          <option value="acknowledged">Reconhecido</option>
          <option value="resolved">Resolvido</option>
        </select>
      </label>
    `;
    return;
  }
  filters.innerHTML = (config.filters || []).map((label) => `
    <label>${label}<input placeholder="${label}" data-filter="${label}" /></label>
  `).join("");
}

function currentRouteConfig() {
  return routes[window.location.pathname] || routes["/cameras"];
}

function activeRouteKey(path = window.location.pathname) {
  if (path === "/settings" || path.startsWith("/settings/")) return "/settings/cameras";
  if (path === "/" || path === "/dashboard" || path === "/operations-view") return "/operations-view";
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
  const next = encodeURIComponent(window.location.pathname || "/operations-view");
  return `
    <div class="cx-empty-state">
      <strong>Login necessário</strong>
      <p>Entre para carregar ${String(config.title || "esta área").toLowerCase()} e proteger os dados do cliente.</p>
      <a class="cx-primary-action" href="/settings/cameras?next=${next}#login">Entrar</a>
    </div>
  `;
}

function usesProductMemoryShell(path) {
  return path === "/operations-view" || path === "/events" || path === "/insights";
}

function renderOperationsAuthState() {
  title.textContent = "";
  heading.textContent = "";
  subtitle.textContent = "";
  tableTitle.textContent = "";
  tableHint.textContent = "";
  primaryAction.textContent = "Entrar";
  primaryAction.onclick = () => {
    window.location.href = "/settings/cameras?next=%2Foperations-view#login";
  };
  cards.innerHTML = `
    <section class="cx-ops-page">
      <div class="cx-ops-title">
        <span>Operations</span>
        <h2>Como está sua operação?</h2>
      </div>
      <section class="cx-ops-auth cx-ops-empty">
        <strong>Entre para acessar os dados da operação.</strong>
        <p>A Campex protege os dados operacionais do cliente. Faça login para carregar esta instalação.</p>
        <a class="cx-primary-action" href="/settings/cameras?next=%2Foperations-view#login">Entrar</a>
      </section>
    </section>
  `;
  renderTabs({ tabs: [] });
  renderFilters({ filters: [] });
  rowsCache = [];
  grid.style.display = "none";
  head.innerHTML = "";
  body.innerHTML = "";
  document.querySelector(".cx-panel")?.classList.add("cx-ops-hide-panel");
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
  const useGrid = config.card && (viewMode === "grid" || path === "/cameras" || path === "/evidence" || path === "/events");
  grid.style.display = useGrid ? "grid" : "none";
  grid.innerHTML = useGrid ? (rows.length ? rows.map(config.card).join("") : emptyState(config)) : "";
  openEventFromQuery(config, rowsCache);
}

function openEventFromQuery(config, rows) {
  if (config.title !== "Events") return;
  const params = new URLSearchParams(window.location.search);
  const eventUuid = params.get("event_uuid");
  const eventId = params.get("event_id") || params.get("id");
  if (!eventUuid && !eventId) return;
  const event = rows.find((item) => item.event_uuid === eventUuid || item.id === eventId);
  if (event) {
    window.history.replaceState({ path: window.location.pathname }, "", window.location.pathname);
    openDrawer(event, config);
  }
}

function renderNotFound(path = window.location.pathname) {
  const config = {
    title: "Página não encontrada",
    heading: "Página não encontrada",
    subtitle: "O endereço acessado não corresponde a nenhuma área da plataforma.",
    columns: ["Mensagem"],
    action: "Voltar para Operations",
    actionHref: "/operations-view",
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
  primaryAction.textContent = "Voltar para Operations";
  primaryAction.onclick = () => { window.location.href = "/operations-view"; };
  document.querySelectorAll("[data-route], .cx-nav a").forEach((link) => {
    link.classList.remove("active");
    link.setAttribute("aria-current", "false");
  });
}

async function openDrawer(row, config) {
  drawer.classList.add("open");
  drawer.setAttribute("aria-hidden", "false");
  drawerContent.innerHTML = "<p>Carregando detalhe...</p>";
  let detailRow = row;
  if (config.title === "Events" && row?.id) {
    detailRow = await requestJson(`/eventos/${row.id}/detail`).catch(() => row);
  }
  drawerContent.innerHTML = config.detail ? config.detail(detailRow) : `<h2>${config.title}</h2><pre>${JSON.stringify(detailRow, null, 2)}</pre>`;
  drawer.querySelector("h2")?.setAttribute("id", "workspaceDrawerTitle");
  drawer.focus({ preventScroll: true });
}

async function loadPage(path = window.location.pathname) {
  const config = routes[path];
  if (!config) {
    renderNotFound(path);
    return;
  }
  document.body.classList.toggle("cx-operations-mode", path === "/operations-view");
  document.body.classList.toggle("cx-events-mode", path === "/events");
  document.body.classList.toggle("cx-intelligence-mode", path === "/insights");
  if (path !== "/operations-view" && path !== "/insights") {
    document.querySelector(".cx-panel")?.classList.remove("cx-ops-hide-panel");
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
  title.textContent = path === "/events" ? "Memória operacional" : config.title;
  heading.textContent = config.heading;
  subtitle.textContent = config.subtitle;
  tableTitle.textContent = path === "/events" ? "Eventos registrados" : config.title;
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
  cards.innerHTML = usesProductMemoryShell(path) ? "" : [
    `<article><strong id="workspaceCount">—</strong><span>Registros</span></article>`,
    `<article><strong>Local</strong><span>SQLite persistente</span></article>`,
    `<article><strong>Seguro</strong><span>Sem credenciais no navegador</span></article>`,
  ].join("");
  renderTabs(config);
  renderFilters(config);
  try {
    const auth = await authStatus();
    if (!auth.authenticated && !auth.bootstrap && config.endpoint !== "/health") {
      if (path === "/operations-view") {
        renderOperationsAuthState();
        document.querySelector(".cx-main")?.scrollTo({ top: 0, behavior: "smooth" });
        return;
      }
      rowsCache = [];
      const workspaceCount = document.querySelector("#workspaceCount");
      if (workspaceCount) workspaceCount.textContent = "—";
      head.innerHTML = `<tr>${config.columns.map((column) => `<th>${column}</th>`).join("")}</tr>`;
      body.innerHTML = `<tr><td colspan="${config.columns.length}">${loginState(config)}</td></tr>`;
      grid.style.display = "none";
      document.querySelector(".cx-main")?.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }
    if (config.customRender) {
      await config.customRender(config);
      document.querySelector(".cx-main")?.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }
    const payload = config.load ? await config.load() : await requestJson(config.endpoint);
    let rows = config.transform ? config.transform(payload) : Array.isArray(payload) ? payload : payload.events || payload.deliveries || payload.recipients || payload.machines || [];
    rows = Array.isArray(rows) ? rows : [];
    rowsCache = config.filterRows ? config.filterRows(rows) : rows;
    const workspaceCount = document.querySelector("#workspaceCount");
    if (workspaceCount) workspaceCount.textContent = rowsCache.length;
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
  if (currentRouteConfig().customRender) {
    operationsSelectedPeriod = operationPeriod();
    loadPage(window.location.pathname);
    return;
  }
  viewMode = currentTab === "lista" ? "list" : currentTab === "grade" ? "grid" : viewMode;
  renderRows(currentRouteConfig());
});

filters.addEventListener("change", (event) => {
  const periodSelect = event.target.closest("#operationsPeriod");
  if (periodSelect) {
    operationsSelectedPeriod = periodSelect.value;
    loadPage(window.location.pathname);
  }
});

document.body.addEventListener("click", async (event) => {
  const trace = event.target.closest("[data-event-uuids]");
  if (trace) {
    const uuids = String(trace.dataset.eventUuids || "").split(",").filter(Boolean);
    renderTraceDrawer(uuids);
    return;
  }

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
  const workflowButton = event.target.closest("[data-event-workflow-action]");
  if (workflowButton) {
    const form = workflowButton.closest("[data-event-workflow-form]");
    const status = form?.querySelector("[data-event-workflow-status]");
    const data = new FormData(form);
    const payload = {
      confirmed_cause: String(data.get("confirmed_cause") || "").trim() || null,
      action_taken: String(data.get("action_taken") || "").trim() || null,
      human_notes: String(data.get("human_notes") || "").trim() || null,
    };
    const eventId = workflowButton.dataset.eventId;
    const action = workflowButton.dataset.eventWorkflowAction;
    workflowButton.textContent = "Salvando...";
    try {
      const path = action === "acknowledge"
        ? `/eventos/${eventId}/acknowledge`
        : action === "resolve"
          ? `/eventos/${eventId}/resolve`
          : `/eventos/${eventId}/human-context`;
      const method = action === "save-human" ? "PATCH" : "POST";
      const updated = await requestJson(path, { method, body: JSON.stringify(payload) });
      if (status) status.textContent = "Evento atualizado.";
      drawerContent.innerHTML = eventDetail(updated);
    } catch (error) {
      if (status) status.textContent = `Erro: ${error.message}`;
      workflowButton.textContent = "Erro";
    }
    return;
  }
  const ruleForm = event.target.closest("#visualRuleForm");
  if (ruleForm && event.type === "submit") return;
  const row = event.target.closest("[data-row-index]");
  const menu = event.target.closest("[data-open-detail]");
  if (!row && !menu) return;
  const index = row ? Number(row.dataset.rowIndex) : 0;
  await openDrawer(rowsCache.filter(matchesTab).filter(includesSearch)[index] || rowsCache[0], currentRouteConfig());
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
