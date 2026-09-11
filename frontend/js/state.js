export const routes = {
  live: {
    title: "Ao vivo",
    message: "Monitoramento ao vivo de uma camera com Vision overlay.",
  },
  events: {
    title: "Eventos",
    message: "Modulo de eventos ainda nao implementado.",
  },
  investigations: {
    title: "Investigações",
    message: "Modulo de investigações ainda nao implementado.",
  },
  cameras: {
    title: "Câmeras",
    message: "Gerenciamento de fontes de camera.",
  },
  zones: {
    title: "Áreas & zonas",
    message: "Modulo de areas e zonas ainda nao implementado.",
  },
  rules: {
    title: "Regras",
    message: "Modulo de regras ainda nao implementado.",
  },
  settings: {
    title: "Configurações",
    message: "Modulo de configuracoes ainda nao implementado.",
  },
};

export function currentRoute() {
  const route = window.location.hash.replace("#", "");
  return routes[route] ? route : "live";
}
