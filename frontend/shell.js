const shellState = {
  popover: null,
  lastFocused: null,
};

function routeKey(pathname = window.location.pathname) {
  if (pathname === "/settings" || pathname.startsWith("/settings/")) return "/settings/cameras";
  if (pathname === "/overview") return "/overview";
  if (pathname === "/dashboard" || pathname === "/") return "/dashboard";
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
  popover.innerHTML = `<strong>${title}</strong>${items.map((item) => `<button type="button" role="menuitem">${item}</button>`).join("")}`;
  document.body.appendChild(popover);
  shellState.popover = popover;
  popover.focus();
}

function setupActiveNavigation() {
  const current = routeKey();
  document.querySelectorAll(".cx-nav a").forEach((link) => {
    const href = new URL(link.href, window.location.origin).pathname;
    const active = routeKey(href) === current;
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
    const iconButton = event.target.closest(".cx-icon-button");
    if (iconButton) {
      const label = iconButton.getAttribute("aria-label") || "Menu";
      openPopover(iconButton, label, label.includes("Notifica") ? ["Nenhuma notificação nova", "Abrir alertas"] : ["Central de ajuda", "Status do sistema"]);
      return;
    }

    const workspaceSwitcher = event.target.closest(".cx-workspace-switcher");
    if (workspaceSwitcher) {
      openPopover(workspaceSwitcher, "Workspace", ["FL Plásticos · Unidade principal", "Gerenciar unidades"]);
      return;
    }

    const rowMenu = event.target.closest(".cx-row-menu:not([data-open-detail])");
    if (rowMenu) {
      openPopover(rowMenu, "Ações", ["Abrir detalhes", "Copiar referência", "Ir para eventos"]);
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
