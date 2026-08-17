const shellState = {
  popover: null,
  lastFocused: null,
  user: null,
  authenticated: false,
};

function routeKey(pathname = window.location.pathname, search = window.location.search) {
  if (pathname === "/operations-view" && new URLSearchParams(search).get("view") === "home") return "/operations-view?view=home";
  if (pathname === "/settings" || pathname.startsWith("/settings/")) return "/settings/cameras";
  if (pathname === "/overview") return "/overview";
  if (pathname === "/dashboard" || pathname === "/" || pathname === "/operations-view") return "/operations-view";
  return pathname;
}

function closePopover() {
  if (shellState.popover) {
    shellState.popover.remove();
    shellState.popover = null;
  }
}

function closeDrawer() {
  document.body.classList.remove("sidebar-open");
  document.querySelector(".cx-mobile-overlay")?.setAttribute("hidden", "");
  document.querySelector(".cx-mobile-menu")?.setAttribute("aria-expanded", "false");
  document.querySelectorAll(".cx-collapse").forEach((button) => button.setAttribute("aria-expanded", "false"));
}

function closeSidePanels() {
  document.querySelectorAll(".cx-detail-drawer.open").forEach((panel) => {
    panel.classList.remove("open");
    panel.setAttribute("aria-hidden", "true");
  });
  if (shellState.lastFocused) shellState.lastFocused.focus({ preventScroll: true });
}

function sanitize(text) {
  const value = String(text ?? "");
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function initialsFrom(name, fallback = "C") {
  const words = String(name || "").trim().split(/\s+/).filter(Boolean);
  if (!words.length) return fallback;
  return words.slice(0, 2).map((word) => word[0]).join("").toUpperCase();
}

function popoverItem(item) {
  if (typeof item === "string") return `<span class="cx-popover-note">${sanitize(item)}</span>`;
  const label = sanitize(item.label);
  const icon = item.icon ? `<span class="cx-nav-icon" data-icon="${sanitize(item.icon)}"></span>` : "";
  const attrs = [
    item.action ? `data-popover-action="${sanitize(item.action)}"` : "",
    item.href ? `href="${sanitize(item.href)}"` : "",
    item.disabled ? "aria-disabled=\"true\"" : "",
  ].filter(Boolean).join(" ");
  if (item.href && !item.disabled) {
    return `<a role="menuitem" ${attrs}>${icon}<span>${label}</span></a>`;
  }
  return `<button type="button" role="menuitem" ${attrs} ${item.disabled ? "disabled" : ""}>${icon}<span>${label}</span></button>`;
}

function openPopover(anchor, title, items) {
  closePopover();
  shellState.lastFocused = anchor;
  const rect = anchor.getBoundingClientRect();
  const popover = document.createElement("div");
  popover.className = "cx-popover";
  popover.setAttribute("role", "menu");
  popover.tabIndex = -1;
  popover.style.top = `${rect.bottom + window.scrollY + 8}px`;
  popover.style.left = `${Math.max(12, rect.right + window.scrollX - 220)}px`;
  popover.innerHTML = `<strong>${sanitize(title)}</strong>${items.map(popoverItem).join("")}`;
  document.body.appendChild(popover);
  shellState.popover = popover;
  popover.focus();
}

async function loadShellUser() {
  try {
    const response = await fetch("/auth/status", { headers: { "Accept": "application/json" } });
    if (!response.ok) return { authenticated: false, user: null, bootstrap: false };
    return response.json();
  } catch {
    return { authenticated: false, user: null, bootstrap: false };
  }
}

function updateIdentity(auth) {
  shellState.authenticated = Boolean(auth?.authenticated);
  shellState.user = auth?.user || null;
  const user = shellState.user || {};
  const displayName = shellState.authenticated ? (user.nome || user.email || "Usuário Campex") : "Entrar";
  const role = shellState.authenticated ? (user.role || user.funcao || "Usuário") : "Sessão necessária";
  const initials = shellState.authenticated ? initialsFrom(displayName) : "C";

  document.querySelectorAll(".cx-profile-name").forEach((node) => { node.textContent = displayName; });
  document.querySelectorAll(".cx-profile-role").forEach((node) => { node.textContent = role; });
  document.querySelectorAll(".cx-avatar, .cx-top-avatar").forEach((node) => { node.textContent = initials; });
  document.querySelectorAll(".cx-profile-trigger").forEach((node) => {
    node.setAttribute("aria-label", shellState.authenticated ? `Conta de ${displayName}` : "Entrar na Campex");
  });
}

function setupActiveNavigation() {
  const current = routeKey();
  document.querySelectorAll(".cx-nav a").forEach((link) => {
    const url = new URL(link.href, window.location.origin);
    const active = routeKey(url.pathname, url.search) === current;
    link.classList.toggle("active", active);
    link.setAttribute("aria-current", active ? "page" : "false");
    const label = link.textContent.trim();
    link.setAttribute("title", label);
    link.setAttribute("aria-label", label);
  });
  document.querySelectorAll(".cx-footer-link").forEach((link) => {
    const label = link.textContent.trim();
    link.setAttribute("title", label);
    link.setAttribute("aria-label", label);
  });
}

function setupSidebar() {
  const sidebar = document.querySelector(".cx-sidebar");
  if (!sidebar) return;
  const overlay = document.createElement("button");
  overlay.className = "cx-mobile-overlay";
  overlay.type = "button";
  overlay.hidden = true;
  overlay.setAttribute("aria-label", "Fechar navegação");
  document.body.appendChild(overlay);
  overlay.addEventListener("click", closeDrawer);

  const mobileMenu = document.createElement("button");
  mobileMenu.className = "cx-mobile-menu";
  mobileMenu.type = "button";
  mobileMenu.setAttribute("aria-label", "Abrir navegação");
  mobileMenu.setAttribute("aria-expanded", "false");
  mobileMenu.innerHTML = "☰";
  document.body.appendChild(mobileMenu);
  mobileMenu.addEventListener("click", () => {
    const open = !document.body.classList.contains("sidebar-open");
    document.body.classList.toggle("sidebar-open", open);
    overlay.hidden = !open;
    mobileMenu.setAttribute("aria-expanded", String(open));
    document.querySelectorAll(".cx-collapse").forEach((button) => button.setAttribute("aria-expanded", String(open)));
    if (open) sidebar.querySelector("a, button")?.focus({ preventScroll: true });
  });

  document.querySelectorAll(".cx-collapse").forEach((button) => {
    button.setAttribute("aria-expanded", "true");
    button.addEventListener("click", () => {
      const mobile = window.matchMedia("(max-width: 860px)").matches;
      if (mobile) {
        const open = !document.body.classList.contains("sidebar-open");
        document.body.classList.toggle("sidebar-open", open);
        overlay.hidden = !open;
        button.setAttribute("aria-expanded", String(open));
        mobileMenu.setAttribute("aria-expanded", String(open));
        if (open) sidebar.querySelector("a, button")?.focus({ preventScroll: true });
        return;
      }
      document.body.classList.toggle("sidebar-collapsed");
      button.setAttribute("aria-expanded", String(!document.body.classList.contains("sidebar-collapsed")));
    });
  });
}

function setupGlobalButtons() {
  document.addEventListener("click", (event) => {
    const popoverAction = event.target.closest("[data-popover-action]");
    if (popoverAction) {
      const action = popoverAction.dataset.popoverAction;
      if (action === "logout") {
        fetch("/auth/logout", { method: "POST" })
          .finally(() => { window.location.href = "/settings/cameras#login"; });
      }
      if (action === "copy-location") {
        navigator.clipboard?.writeText(window.location.href).catch(() => {});
        closePopover();
      }
      return;
    }

    const profile = event.target.closest(".cx-profile-trigger, .cx-top-avatar");
    if (profile) {
      const user = shellState.user || {};
      const userLine = shellState.authenticated
        ? `${user.email || user.nome || "Usuário autenticado"}`
        : "Entre para acessar dados protegidos.";
      const profileItems = shellState.authenticated ? [
        userLine,
        { label: "Configurações", href: "/settings/cameras", icon: "settings" },
        { label: "Diagnóstico/status", href: "/local-diagnostics-view", icon: "status" },
        { label: "Sair", action: "logout", icon: "logout" },
      ] : [
        userLine,
        { label: "Entrar", href: "/settings/cameras#login", icon: "users" },
      ];
      openPopover(profile, shellState.authenticated ? "Conta" : "Sessão", profileItems);
      return;
    }

    const iconButton = event.target.closest(".cx-icon-button");
    if (iconButton) {
      const label = iconButton.getAttribute("aria-label") || "Menu";
      openPopover(iconButton, label, label.includes("Notifica")
        ? ["Nenhuma notificação nova", { label: "Abrir Events", href: "/events", icon: "events" }]
        : [{ label: "Ajuda", href: "/help", icon: "help" }, { label: "Diagnóstico/status", href: "/local-diagnostics-view", icon: "status" }]);
      return;
    }

    const workspaceSwitcher = event.target.closest(".cx-workspace-switcher");
    if (workspaceSwitcher) {
      const currentWorkspace = workspaceSwitcher.getAttribute("title") || "Cliente piloto · Unidade principal";
      openPopover(workspaceSwitcher, "Workspace", [currentWorkspace, { label: "Configurar operação", href: "/settings/cameras", icon: "settings" }]);
      return;
    }

    const rowMenu = event.target.closest(".cx-row-menu:not([data-open-detail])");
    if (rowMenu) {
      openPopover(rowMenu, "Ações", [{ label: "Copiar referência", action: "copy-location" }, { label: "Ir para Events", href: "/events", icon: "events" }]);
      return;
    }

    if (shellState.popover && !event.target.closest(".cx-popover")) closePopover();
  });
}

function setupKeyboard() {
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closePopover();
      closeSidePanels();
      closeDrawer();
    }
  });
}

setupActiveNavigation();
setupSidebar();
setupGlobalButtons();
setupKeyboard();
loadShellUser().then(updateIdentity);
