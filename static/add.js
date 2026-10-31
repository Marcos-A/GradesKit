// Add-grades tool: send the master list and the grades to the server, show
// the student matching and copy the master list with the new column. As in
// the fill tool, all decisions are made server-side.

(() => {
  const NO_HEADER = -1;
  const NO_STUDENT = -1;
  const HEADER_ROW_CHOICES = 15;
  const STATUS_LABELS = {
    exact: "Coincideix",
    probable: "Semblant",
    manual: "Triat a mà",
    ambiguous: "Dubtós",
    none: "Sense nota",
  };

  const panel = document.getElementById("panel-add");
  const alerts = document.getElementById("add-alerts");
  const review = document.getElementById("add-review");
  const masterHeaderSelect = document.getElementById("add-master-header-row");
  const masterNameSelect = document.getElementById("add-master-name-column");
  const gradesHeaderSelect = document.getElementById("add-grades-header-row");
  const gradesNameSelect = document.getElementById("add-grades-name-column");
  const gradesGradeSelect = document.getElementById("add-grades-grade-column");
  const matchSection = document.getElementById("add-match-section");
  const summary = document.getElementById("add-summary");
  const warnings = document.getElementById("add-warnings");
  const matchBody = document.getElementById("add-match-body");
  const resultGroup = document.getElementById("add-result-group");
  const resultPreview = document.getElementById("add-result");
  const copyButton = document.getElementById("add-copy");
  const copyStatus = document.getElementById("add-copy-status");

  // One entry per input list ("master" and "grades"), each with its own
  // paste box and CSV upload.
  const parts = {};
  for (const step of panel.querySelectorAll("[data-part]")) {
    parts[step.dataset.part] = {
      source: "paste",
      file: null,
      segments: Array.from(step.querySelectorAll(".segment")),
      pasteBlock: step.querySelector('[data-block="paste"]'),
      fileBlock: step.querySelector('[data-block="file"]'),
      text: step.querySelector("textarea"),
      input: step.querySelector('input[type="file"]'),
      zone: step.querySelector(".upload-zone"),
      status: step.querySelector("[data-status]"),
    };
  }

  const state = {
    options: emptyOptions(),
    result: null,
    requestId: 0,
  };

  function emptyOptions() {
    return {
      master_header_row: null,
      master_name_column: null,
      grades_header_row: null,
      grades_name_column: null,
      grades_grade_column: null,
      matches: {},
    };
  }

  function hasInput(part) {
    return part.source === "paste" ? part.text.value.trim() !== "" : part.file !== null;
  }

  function buildFormData() {
    const formData = new FormData();
    for (const [name, part] of Object.entries(parts)) {
      if (part.source === "file" && part.file) {
        formData.append(`${name}_file`, part.file, part.file.name);
      } else if (part.source === "paste") {
        formData.append(`${name}_text`, part.text.value);
      }
    }
    formData.append("options", JSON.stringify(state.options));
    return formData;
  }

  // --- Server round trips -------------------------------------------------

  async function refreshPreview() {
    copyStatus.textContent = "";
    if (!Object.values(parts).some(hasInput)) {
      state.result = null;
      showError(alerts, "");
      render();
      return;
    }

    // Ignore responses that arrive after a newer request was sent.
    const requestId = ++state.requestId;
    const response = await fetch("/api/add-grades/preview", { method: "POST", body: buildFormData() });
    if (requestId !== state.requestId) {
      return;
    }
    if (!response.ok) {
      state.result = null;
      showError(alerts, await readError(response));
      render();
      return;
    }
    showError(alerts, "");
    state.result = await response.json();
    render();
  }

  let previewTimer = null;
  function schedulePreview(delay = 0) {
    window.clearTimeout(previewTimer);
    previewTimer = window.setTimeout(refreshPreview, delay);
  }

  // The Clipboard API needs HTTPS (or localhost); the hidden textarea keeps
  // the button working elsewhere.
  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      const field = document.createElement("textarea");
      field.value = text;
      field.setAttribute("readonly", "");
      field.style.position = "fixed";
      field.style.opacity = "0";
      document.body.appendChild(field);
      field.select();
      const copied = document.execCommand("copy");
      field.remove();
      return copied;
    }
  }

  async function copyResult() {
    if (!state.result || !state.result.text) return;
    const copied = await copyText(state.result.text);
    copyStatus.textContent = copied
      ? "Copiat. Enganxa’l al full de càlcul (Ctrl+V / ⌘V)."
      : "No s’ha pogut copiar. Torna-ho a provar.";
  }

  // --- Rendering ----------------------------------------------------------

  function option(value, label, selected) {
    return `<option value="${value}"${selected ? " selected" : ""}>${escapeHtml(label)}</option>`;
  }

  function truncate(text, length = 60) {
    return text.length > length ? `${text.slice(0, length - 1)}…` : text;
  }

  function renderFileStatus(part) {
    part.status.innerHTML = part.file
      ? `<span class="upload-chip">${escapeHtml(part.file.name)}</span>`
      : '<span class="upload-placeholder">Encara no s\'ha seleccionat cap fitxer.</span>';
  }

  function headerOptions(list) {
    return [option(NO_HEADER, "Sense capçalera", list.header_row === NO_HEADER)]
      .concat(
        list.rows
          .slice(0, HEADER_ROW_CHOICES)
          .map((row, index) => option(index, `Fila ${index + 1}: ${truncate(row.filter(Boolean).join(" · "))}`, index === list.header_row)),
      )
      .join("");
  }

  function columnOptions(list, selected) {
    return list.columns.map((label, index) => option(index, label, index === selected)).join("");
  }

  function renderSettings(result) {
    const { master, grades } = result;
    for (const select of [masterHeaderSelect, masterNameSelect]) select.closest(".setting").hidden = !master;
    for (const select of [gradesHeaderSelect, gradesNameSelect, gradesGradeSelect]) select.closest(".setting").hidden = !grades;
    if (master) {
      masterHeaderSelect.innerHTML = headerOptions(master);
      masterNameSelect.innerHTML = columnOptions(master, master.name_column);
    }
    if (grades) {
      gradesHeaderSelect.innerHTML = headerOptions(grades);
      gradesNameSelect.innerHTML = columnOptions(grades, grades.name_column);
      gradesGradeSelect.innerHTML = columnOptions(grades, grades.grade_column);
    }
  }

  function renderMatches(result) {
    const counts = result.summary;
    matchSection.hidden = !counts;
    if (!counts) return;

    const pieces = [`<strong>${counts.matched}</strong> de ${counts.students} estudiants tenen nota`];
    if (counts.review) pieces.push(`<strong>${counts.review}</strong> per revisar`);
    if (counts.missing) pieces.push(`${counts.missing} sense nota (reben un 0)`);
    summary.innerHTML = pieces.join(" · ");

    warnings.innerHTML = result.unused.length
      ? `<div class="alert warning">
           ${result.unused.length === 1 ? "Aquest estudiant de les notes no és" : `Aquests ${result.unused.length} estudiants de les notes no són`}
           a la llista principal i la seva nota no s’afegirà:
           ${result.unused.map((student) => `<strong>${escapeHtml(student.name)}</strong> (${escapeHtml(student.grade || "sense nota")})`).join(", ")}.
         </div>`
      : "";

    const studentOptions = result.grades.student_rows.map((row) => [row, result.grades.rows[row][result.grades.name_column]]);
    // Rows that still need a look come first.
    const order = { ambiguous: 0, probable: 1, none: 2 };
    const students = result.students
      .map((student, index) => ({ student, index }))
      .sort((a, b) => (order[a.student.status] ?? 3) - (order[b.student.status] ?? 3) || a.index - b.index)
      .map(({ student }) => student);
    matchBody.innerHTML = students
      .map((student) => {
        const selected = student.grades_row ?? NO_STUDENT;
        const options = [option(NO_STUDENT, "— Sense nota (0) —", selected === NO_STUDENT)]
          .concat(studentOptions.map(([row, name]) => option(row, name, row === selected)))
          .join("");
        const note = student.status === "ambiguous"
          ? `<small class="row-warning">Pot ser ${escapeHtml(student.alternatives.join(" o "))}: tria’n un.</small>`
          : "";
        const rowStatus = student.status === "ambiguous" ? "probable" : student.status;
        return `<tr class="status-${rowStatus}">
          <td>${escapeHtml(student.name)}${note}</td>
          <td><select data-row="${student.row}" aria-label="Estudiant per a ${escapeHtml(student.name)}">${options}</select></td>
          <td class="grade-cell">${escapeHtml(student.grade)}</td>
          <td><span class="status status-badge-${rowStatus}">${STATUS_LABELS[student.status]}</span></td>
        </tr>`;
      })
      .join("");
  }

  function renderResult(result) {
    resultGroup.hidden = !result.output_rows.length;
    if (!result.output_rows.length) return;
    const column = result.output_column;
    const masterHeader = result.master.header_row;
    const students = new Set(result.master.student_rows);
    const body = result.output_rows
      .map((row, rowIndex) => {
        let rowClass = "row-ignored";
        if (rowIndex === masterHeader) rowClass = "row-header";
        else if (students.has(rowIndex)) rowClass = "row-student";
        const cells = row
          .map((cell, columnIndex) => `<td class="${columnIndex === column ? "col-grade" : ""}">${escapeHtml(cell)}</td>`)
          .join("");
        return `<tr class="${rowClass}">${cells}</tr>`;
      })
      .join("");
    const roles = result.output_rows[0].map((_, index) => {
      if (index === result.master.name_column) return '<span class="role role-name">Nom</span>';
      if (index === column) return '<span class="role role-grade">Nova</span>';
      return "";
    });
    resultPreview.innerHTML = `<table><thead><tr>${roles.map((role) => `<th>${role}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table>`;
  }

  function render() {
    for (const part of Object.values(parts)) renderFileStatus(part);
    const result = state.result;
    review.hidden = !(result && (result.master || result.grades));
    if (result && !review.hidden) {
      renderSettings(result);
      renderMatches(result);
      renderResult(result);
    }
    copyButton.disabled = !(result && result.text);
  }

  // --- Inputs ---------------------------------------------------------------

  // A new list changes its rows and columns, so its choices and the manual
  // matches are detected again.
  function resetChoices(name) {
    const prefix = `${name}_`;
    for (const key of Object.keys(state.options)) {
      if (key.startsWith(prefix)) state.options[key] = null;
    }
    state.options.matches = {};
  }

  for (const [name, part] of Object.entries(parts)) {
    part.zone.addEventListener("click", () => part.input.click());
    part.zone.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        part.input.click();
      }
    });
    const onFile = (file) => {
      part.file = file;
      resetChoices(name);
      schedulePreview();
    };
    part.input.addEventListener("change", () => {
      const file = part.input.files[0];
      part.input.value = "";
      if (file) onFile(file);
    });
    bindFileDrop(part.zone, part.input, alerts, ([file]) => {
      showError(alerts, "");
      onFile(file);
    });

    part.text.addEventListener("input", () => {
      resetChoices(name);
      schedulePreview(400);
    });

    for (const segment of part.segments) {
      segment.addEventListener("click", () => {
        part.source = segment.dataset.source;
        for (const other of part.segments) {
          const isActive = other === segment;
          other.classList.toggle("is-active", isActive);
          other.setAttribute("aria-pressed", String(isActive));
        }
        part.pasteBlock.hidden = part.source !== "paste";
        part.fileBlock.hidden = part.source !== "file";
        resetChoices(name);
        schedulePreview();
      });
    }
  }

  // Changing a header row or the name column changes which rows are
  // students, so the manual matches start again.
  const settings = [
    [masterHeaderSelect, "master_header_row", true],
    [masterNameSelect, "master_name_column", true],
    [gradesHeaderSelect, "grades_header_row", true],
    [gradesNameSelect, "grades_name_column", true],
    [gradesGradeSelect, "grades_grade_column", false],
  ];
  for (const [select, key, resetsMatches] of settings) {
    select.addEventListener("change", () => {
      state.options[key] = Number(select.value);
      if (resetsMatches) state.options.matches = {};
      schedulePreview();
    });
  }

  matchBody.addEventListener("change", (event) => {
    const select = event.target.closest("select[data-row]");
    if (select) {
      state.options.matches[select.dataset.row] = Number(select.value);
      schedulePreview();
    }
  });

  copyButton.addEventListener("click", copyResult);
  render();
})();
