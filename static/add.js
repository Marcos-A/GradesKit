// Add-grades tool: send the master list and the grades to the server, show
// the student matching and copy each student's selected grades, with or
// without the name. As in the fill tool, matching is done server-side.

(() => {
  const NO_HEADER = -1;
  const NO_STUDENT = -1;
  const HEADER_ROW_CHOICES = 15;
  const OUTPUT_KEY = "gradeskit.add.output";
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
  const inputWarnings = document.getElementById("add-input-warnings");
  const masterHeaderSelect = document.getElementById("add-master-header-row");
  const masterNameSelect = document.getElementById("add-master-name-column");
  const gradesHeaderSelect = document.getElementById("add-grades-header-row");
  const gradesNameSelect = document.getElementById("add-grades-name-column");
  const gradeSelection = document.getElementById("add-grade-selection");
  const gradeColumns = document.getElementById("add-grade-columns");
  const gradeSelectionHint = document.getElementById("add-grade-selection-hint");
  const matchSection = document.getElementById("add-match-section");
  const summary = document.getElementById("add-summary");
  const warnings = document.getElementById("add-warnings");
  const matchHead = document.getElementById("add-match-head");
  const matchBody = document.getElementById("add-match-body");
  const resultGroup = document.getElementById("add-result-group");
  const resultPreview = document.getElementById("add-result");
  const resultNote = document.getElementById("add-result-note");
  const outputSegments = Array.from(document.querySelectorAll("#add-output .segment"));
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
      grades_grade_columns: null,
      matches: {},
      output: savedOutput(),
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

  async function refreshPreview(requestId) {
    if (!Object.values(parts).some(hasInput)) {
      state.result = null;
      showError(alerts, "");
      render();
      return;
    }

    let result = null;
    let error = "";
    try {
      const response = await fetch("/api/add-grades/preview", { method: "POST", body: buildFormData() });
      if (response.ok) result = await response.json();
      else error = await readError(response);
    } catch {
      error = "No s’ha pogut actualitzar la vista prèvia. Torna-ho a provar.";
    }
    if (requestId !== state.requestId) return;
    state.result = result;
    showError(alerts, error);
    render();
  }

  let previewTimer = null;
  function schedulePreview(delay = 0) {
    // A change invalidates the old clipboard text while its preview loads.
    const requestId = ++state.requestId;
    copyButton.disabled = true;
    copyStatus.textContent = "";
    window.clearTimeout(previewTimer);
    previewTimer = window.setTimeout(() => refreshPreview(requestId), delay);
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
    if (copyButton.disabled) return;
    const requestId = state.requestId;
    const copied = await copyText(state.result.text);
    if (requestId !== state.requestId) return;
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
    for (const select of [gradesHeaderSelect, gradesNameSelect]) select.closest(".setting").hidden = !grades;
    gradeSelection.hidden = !grades;
    if (master) {
      masterHeaderSelect.innerHTML = headerOptions(master);
      masterNameSelect.innerHTML = columnOptions(master, master.name_column);
    }
    if (grades) {
      gradesHeaderSelect.innerHTML = headerOptions(grades);
      gradesNameSelect.innerHTML = columnOptions(grades, grades.name_column);
      renderGradeSelection(grades);
    }
  }

  function renderGradeSelection(grades) {
    // Reuse the checkbox elements across previews to keep keyboard focus.
    const layout = JSON.stringify([grades.columns, grades.name_column]);
    if (gradeColumns.dataset.layout !== layout) {
      gradeColumns.innerHTML = grades.columns.map((label, index) => {
        if (index === grades.name_column) return "";
        return `<label class="chip-toggle"><input type="checkbox" value="${index}"><span>${escapeHtml(label)}</span></label>`;
      }).join("");
      gradeColumns.dataset.layout = layout;
    }
    const selected = new Set(grades.grade_columns);
    for (const input of gradeColumns.querySelectorAll("input")) {
      input.checked = selected.has(Number(input.value));
    }
    syncGradeSelection();
    showGradeSelectionHint(selected.size);
  }

  function showGradeSelectionHint(count) {
    gradeSelectionHint.textContent = count ? "" : "Tria com a mínim una columna.";
    gradeSelectionHint.hidden = count > 0;
  }

  function renderMatches(result, gradeLabels) {
    const counts = result.summary;
    matchSection.hidden = !counts;
    if (!counts) return;

    const pieces = [`<strong>${counts.matched}</strong> de ${counts.students} estudiants amb correspondència`];
    if (counts.review) pieces.push(`<strong>${counts.review}</strong> per revisar`);
    if (counts.missing) pieces.push(`${counts.missing} sense correspondència${gradeLabels.length ? " (reben un 0 a cada columna)" : ""}`);
    summary.innerHTML = pieces.join(" · ");

    warnings.innerHTML = result.unused.length
      ? `<div class="alert warning">
           ${result.unused.length === 1 ? "Aquest estudiant de les notes no és" : `Aquests ${result.unused.length} estudiants de les notes no són`}
           a la llista principal:
           ${result.unused.map((student) => {
             const values = student.grades.length ? ` (${escapeHtml(student.grades.join(" · "))})` : "";
             return `<strong>${escapeHtml(student.name)}</strong>${values}`;
           }).join(", ")}.
         </div>`
      : "";

    matchHead.innerHTML = `<tr>
      <th scope="col">Estudiant de la llista principal</th>
      <th scope="col">Estudiant a les notes</th>
      ${gradeLabels.map((label) => `<th scope="col">${escapeHtml(label)}</th>`).join("")}
      <th scope="col">Estat</th>
    </tr>`;
    const studentOptions = result.grades.student_rows.map((row) => [row, result.grades.rows[row][result.grades.name_column]]);
    // Alphabetical with Catalan rules, so accents don't push names to the end
    // ("Àvila" sorts with "Avila"); the copied result keeps the main list's order.
    const collator = new Intl.Collator("ca", { sensitivity: "base", numeric: true });
    const students = result.students.slice().sort((a, b) => collator.compare(a.name, b.name));
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
          ${student.grades.map((grade) => `<td class="grade-cell">${escapeHtml(grade)}</td>`).join("")}
          <td><span class="status status-badge-${rowStatus}">${STATUS_LABELS[student.status]}</span></td>
        </tr>`;
      })
      .join("");
  }

  function renderResult(result, gradeLabels) {
    resultGroup.hidden = !result.output_rows.length;
    if (!result.output_rows.length) return;
    const withName = state.options.output === "name_grade";
    for (const segment of outputSegments) {
      const isActive = segment.dataset.output === state.options.output;
      segment.classList.toggle("is-active", isActive);
      segment.setAttribute("aria-pressed", String(isActive));
    }
    // The result starts after the master's header row; name it, so a
    // student taken for a header is easy to spot.
    const header = result.master.header_row;
    resultNote.textContent = header === NO_HEADER
      ? ""
      : `No s’inclou la fila ${header + 1} de la llista principal («${truncate(result.master.rows[header].filter(Boolean).join(" · "))}») ni les anteriors. Si és un estudiant, tria «Sense capçalera» a dalt.`;
    const students = new Set(result.master.student_rows);
    const body = result.output_rows
      .map((row, rowIndex) => {
        const rowClass = students.has(rowIndex + result.output_first_row) ? "row-student" : "row-ignored";
        const cells = row
          .map((cell, index) => `<td${withName && index === 0 ? "" : ' class="col-grade"'}>${escapeHtml(cell)}</td>`)
          .join("");
        return `<tr class="${rowClass}">${cells}</tr>`;
      })
      .join("");
    const roles = gradeLabels.map((label) => `<span class="role role-grade">${escapeHtml(label)}</span>`);
    if (withName) roles.unshift('<span class="role role-name">Nom</span>');
    resultPreview.innerHTML = `<table><thead><tr>${roles.map((role) => `<th scope="col">${role}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table>`;
  }

  function render() {
    for (const part of Object.values(parts)) renderFileStatus(part);
    const result = state.result;
    inputWarnings.innerHTML = (result ? result.warnings : [])
      .map((warning) => `<div class="alert warning">${escapeHtml(warning)}</div>`)
      .join("");
    review.hidden = !(result && (result.master || result.grades));
    if (result && !review.hidden) {
      renderSettings(result);
      const gradeLabels = result.grades?.grade_columns.map((column) => result.grades.columns[column]) ?? [];
      renderMatches(result, gradeLabels);
      renderResult(result, gradeLabels);
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
    if (name === "grades") gradeSelection.hidden = true;
  }

  function selectSource(part, source) {
    part.source = source;
    for (const segment of part.segments) {
      const isActive = segment.dataset.source === source;
      segment.classList.toggle("is-active", isActive);
      segment.setAttribute("aria-pressed", String(isActive));
    }
    part.pasteBlock.hidden = source !== "paste";
    part.fileBlock.hidden = source !== "file";
  }

  // The output choice is remembered like the paste/CSV choices below.
  function savedOutput() {
    try {
      return localStorage.getItem(OUTPUT_KEY) === "grade" ? "grade" : "name_grade";
    } catch {
      return "name_grade";
    }
  }

  // Each list remembers whether it was last pasted or uploaded, in this
  // browser only. Storage can be blocked (private windows), so failures fall
  // back to pasting.
  const SOURCE_KEY = "gradeskit.add.source.";

  function savedSource(name) {
    try {
      return localStorage.getItem(SOURCE_KEY + name) === "file" ? "file" : "paste";
    } catch {
      return "paste";
    }
  }

  function rememberSource(name, source) {
    try {
      localStorage.setItem(SOURCE_KEY + name, source);
    } catch {
      // Not remembered; the choice still applies until the page is reloaded.
    }
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
        selectSource(part, segment.dataset.source);
        rememberSource(name, part.source);
        resetChoices(name);
        schedulePreview();
      });
    }
    selectSource(part, savedSource(name));
  }

  // Changing a header row or the name column changes which rows are
  // students, so the manual matches start again.
  const settings = [
    [masterHeaderSelect, "master_header_row"],
    [masterNameSelect, "master_name_column"],
    [gradesHeaderSelect, "grades_header_row"],
    [gradesNameSelect, "grades_name_column"],
  ];
  for (const [select, key] of settings) {
    select.addEventListener("change", () => {
      state.options[key] = Number(select.value);
      state.options.matches = {};
      if (key === "grades_name_column") {
        state.options.grades_grade_columns = state.options.grades_grade_columns?.filter((column) => column !== Number(select.value)) ?? null;
      }
      schedulePreview();
    });
  }

  const syncGradeSelection = bindColumnSelection(gradeColumns, document.getElementById("add-grade-select-all"), (selected) => {
    state.options.grades_grade_columns = selected;
    showGradeSelectionHint(selected.length);
    schedulePreview();
  });

  matchBody.addEventListener("change", (event) => {
    const select = event.target.closest("select[data-row]");
    if (select) {
      state.options.matches[select.dataset.row] = Number(select.value);
      schedulePreview();
    }
  });

  for (const segment of outputSegments) {
    segment.addEventListener("click", () => {
      state.options.output = segment.dataset.output;
      try {
        localStorage.setItem(OUTPUT_KEY, state.options.output);
      } catch {
        // Not remembered; the choice still applies until the page is reloaded.
      }
      schedulePreview();
    });
  }

  copyButton.addEventListener("click", copyResult);
  render();
})();
