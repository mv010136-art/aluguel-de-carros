(function () {
  "use strict";

  // Menu móvel
  var toggle = document.querySelector("[data-nav-toggle]");
  var nav = document.querySelector("[data-nav]");
  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      var open = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  // Confirmação antes de ações destrutivas
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.getAttribute("data-confirm"))) {
        event.preventDefault();
      }
    });
  });

  // Estado de carregamento ao enviar formulários
  document.querySelectorAll("form[data-loading]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (event.defaultPrevented) { return; }
      var button = event.submitter || form.querySelector("button[type=submit]");
      if (button) {
        // Adia a marcação para não impedir o envio do valor do botão.
        window.setTimeout(function () { button.classList.add("loading"); }, 0);
      }
    });
  });

  // Galeria da página do veículo
  var main = document.querySelector("[data-gallery-main]");
  document.querySelectorAll("[data-gallery-thumb]").forEach(function (thumb) {
    thumb.addEventListener("click", function () {
      if (!main) { return; }
      var img = main.querySelector("img");
      if (!img) {
        img = document.createElement("img");
        main.textContent = "";
        main.appendChild(img);
      }
      img.src = thumb.getAttribute("data-src");
    });
  });

  // Orçamento em tempo real na página de reserva (cálculo feito no servidor)
  var form = document.getElementById("booking-form");
  var box = document.getElementById("quote-box");
  if (form && box) {
    var url = form.getAttribute("data-quote-url");
    var timer = null;

    var text = function (tag, className, content) {
      var el = document.createElement(tag);
      if (className) { el.className = className; }
      el.textContent = content;
      return el;
    };
    var row = function (label, amount, extra) {
      var div = text("div", "quote-row" + (extra ? " " + extra : ""), "");
      div.appendChild(text("span", "", label));
      div.appendChild(text("strong", "", amount));
      return div;
    };

    var render = function (data) {
      box.textContent = "";
      if (!data.ok) {
        data.errors.forEach(function (message) { box.appendChild(text("div", "message error", message)); });
        return;
      }
      var wrapper = text("div", "quote", "");
      wrapper.appendChild(text("h3", "", "Resumo do orçamento"));
      data.quote.rows.forEach(function (item) { wrapper.appendChild(row(item.label, item.amount)); });
      wrapper.appendChild(row("Total estimado", data.quote.total, "quote-total"));
      wrapper.appendChild(text("p", "muted small", "Valor estimado, recalculado pelo sistema ao enviar a solicitação."));
      box.appendChild(wrapper);
    };

    var update = function () {
      var pickup = form.elements["pickup_at"].value;
      var ret = form.elements["return_at"].value;
      if (!pickup || !ret) { return; }
      var params = new URLSearchParams();
      new FormData(form).forEach(function (value, key) {
        if (key === "pickup_at" || key === "return_at" || key.indexOf("extra_") === 0) {
          params.append(key, value);
        }
      });
      fetch(url + "?" + params.toString(), { headers: { Accept: "application/json" } })
        .then(function (response) { return response.json(); })
        .then(render)
        .catch(function () { /* mantém o último orçamento exibido */ });
    };

    form.addEventListener("change", function () {
      window.clearTimeout(timer);
      timer = window.setTimeout(update, 250);
    });
  }
})();
