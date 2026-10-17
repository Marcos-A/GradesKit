// Fill tool: send the worksheet and the grades to the server, show the
// detected structure and the student matching, and download the filled CSV.
// All decisions are made server-side; this script only renders and collects
// the teacher's choices.

(() => {
  const NO_STUDENT = -1;
  const HEADER_ROW_CHOICES = 15;
  const STATUS_LABELS = {
    exact: "Coincideix",
    confirmed: "Confirmat",
    manual: "Triat a mà",
    probable: "Per confirmar",
    none: "Sense nota",
    excluded: "Exclòs",
  };

  const alerts = document.getElementById("fill-alerts");
  const worksheetInput = document.getElementById("worksheet-input");
  const worksheetZone = document.getElementById("worksheet-zone");
  const worksheetStatus = document.getElementById("worksheet-status");
  const segments = Array.from(document.querySelectorAll(".segment"));
  const pasteBlock = document.getElementById("grades-paste-block");
  const fileBlock = document.getElementById("grades-file-block");
  const gradesText = document.getElementById("grades-text");
  const gradesFileInput = document.getElementById("grades-file-input");
  const gradesZone = document.getElementById("grades-zone");
  const gradesFileStatus = document.getElementById("grades-file-status");
  const review = document.getElementById("fill-review");
  const headerRowSelect = document.getElementById("opt-header-row");
  const nameColumnSelect = document.getElementById("opt-name-column");
  const gradeColumnSelect = document.getElementById("opt-grade-column");
  const layoutSelect = document.getElementById("opt-layout");
  const feedbackColumns = document.getElementById("opt-feedback-columns");
  const sheetPreview = document.getElementById("sheet-preview");
  const feedbackSample = document.getElementById("feedback-sample");
  const matchSection = document.getElementById("match-section");
  const matchSummary = document.getElementById("match-summary");
  const fillWarnings = document.getElementById("fill-warnings");
  const matchBody = document.getElementById("match-body");
  const unusedStudents = document.getElementById("unused-students");
  const downloadButton = document.getElementById("fill-download");

  const state = {
    worksheet: null,
    source: "paste",
    gradesFile: null,
    options: emptyOptions(),
    matches: {},
    result: null,
    requestId: 0,
  };

  function emptyOptions() {
    return { header_row: null, name_column: null, grade_column: null, feedback_columns: null, layout: layoutSelect.value };
  }

  function hasGrades() {
    return state.source === "paste" ? gradesText.value.trim() !== "" : state.gradesFile !== null;
  }

  function buildFormData() {
    const formData = new FormData();
    if (state.worksheet) {
      formData.append("worksheet", state.worksheet, state.worksheet.name);
    }
    if (state.source === "file" && state.gradesFile) {
      formData.append("grades_file", state.gradesFile, state.gradesFile.name);
    } else if (state.source === "paste") {
      formData.append("grades_text", gradesText.value);
    }
    formData.append("options", JSON.stringify({ ...state.options, matches: state.matches }));
    return formData;
  }

  // --- Server round trips -------------------------------------------------

  async function refreshPreview() {
    if (!state.worksheet && !hasGrades()) {
      state.result = null;
      showError(alerts, "");
      render();
      return;
    }

    // Ignore responses that arrive after a newer request was sent.
    const requestId = ++state.requestId;
    const response = await fetch("/api/fill/preview", { method: "POST", body: buildFormData() });
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

  async function download() {
    const response = await fetch("/fill", { method: "POST", body: buildFormData() });
    if (!response.ok) {
      showError(alerts, await readError(response));
      return;
    }
    await downloadResponse(response, "full-omplert.csv");
  }

  // --- Rendering ----------------------------------------------------------

  function option(value, label, selected) {
    return `<option value="${value}"${selected ? " selected" : ""}>${escapeHtml(label)}</option>`;
  }

  function truncate(text, length = 60) {
    return text.length > length ? `${text.slice(0, length - 1)}…` : text;
  }

  function renderWorksheetStatus() {
    const info = state.result && state.result.worksheet;
    if (!state.worksheet) {
      worksheetStatus.innerHTML = '<span class="upload-placeholder">Encara no s\'ha seleccionat cap fitxer.</span>';
      return;
    }
    const chip = `<span class="upload-chip">${escapeHtml(state.worksheet.name)}</span>`;
    if (!info) {
      worksheetStatus.innerHTML = chip;
      return;
    }
    const details = [
      `Moodle en ${info.language_name}`,
      `${info.participants} participants`,
      info.max_grade !== null ? `qualificació màxima ${String(info.max_grade).replace(".", ",")}` : null,
    ].filter(Boolean);
    worksheetStatus.innerHTML = `${chip}<span class="upload-detail">${escapeHtml(details.join(" · "))}</span>`;
  }

  function renderGradesFileStatus() {
    gradesFileStatus.innerHTML = state.gradesFile
      ? `<span class="upload-chip">${escapeHtml(state.gradesFile.name)}</span>`
      : '<span class="upload-placeholder">Encara no s\'ha seleccionat cap fitxer.</span>';
  }

  function renderSettings(grades) {
    headerRowSelect.innerHTML = grades.rows
      .slice(0, HEADER_ROW_CHOICES)
      .map((row, index) => option(index, `Fila ${index + 1}: ${truncate(row.filter(Boolean).join(" · "))}`, index === grades.header_row))
      .join("");
    nameColumnSelect.innerHTML = grades.columns
      .map((label, index) => option(index, label, index === grades.name_column))
      .join("");
    gradeColumnSelect.innerHTML = grades.columns
      .map((label, index) => option(index, label + (index === grades.columns.length - 1 ? " (última columna)" : ""), index === grades.grade_column))
      .join("");
    feedbackColumns.innerHTML = grades.columns
      .map((label, index) => {
        if (index === grades.name_column) {
          return "";
        }
        const checked = grades.feedback_columns.includes(index) ? " checked" : "";
        return `<label class="chip-toggle"><input type="checkbox" value="${index}"${checked}><span>${escapeHtml(label)}</span></label>`;
      })
      .join("");
  }

  function renderSheetPreview(grades) {
    const roles = grades.columns.map((_, index) => {
      if (index === grades.name_column) return '<span class="role role-name">Nom</span>';
      if (index === grades.grade_column) return '<span class="role role-grade">Qualificació</span>';
      if (grades.feedback_columns.includes(index)) return '<span class="role">Comentari</span>';
      return "";
    });
    const studentRows = new Set(grades.student_rows);
    const footerRows = new Set(grades.footer_rows);

    const body = grades.rows
      .map((row, rowIndex) => {
        let rowClass = "row-ignored";
        if (rowIndex < grades.header_row) rowClass = "row-title";
        else if (rowIndex === grades.header_row) rowClass = "row-header";
        else if (studentRows.has(rowIndex)) rowClass = "row-student";
        else if (footerRows.has(rowIndex)) rowClass = "row-footer";
        const cells = row
          .map((cell, columnIndex) => {
            const classes = [];
            if (columnIndex === grades.grade_column) classes.push("col-grade");
            if (columnIndex === grades.name_column) classes.push("col-name");
            if (!grades.feedback_columns.includes(columnIndex) && columnIndex !== grades.name_column) classes.push("col-off");
            return `<td class="${classes.join(" ")}">${escapeHtml(cell)}</td>`;
          })
          .join("");
        return `<tr class="${rowClass}">${cells}</tr>`;
      })
      .join("");
    sheetPreview.innerHTML = `<table><thead><tr>${roles.map((role) => `<th>${role}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table>`;
  }

  function renderMatches(result) {
    const grades = result.grades;
    const summary = result.summary;
    matchSection.hidden = !summary;
    if (!summary) {
      return;
    }

    const parts = [`<strong>${summary.applied}</strong> de ${summary.participants} participants s’ompliran`];
    if (summary.pending) parts.push(`<strong>${summary.pending}</strong> per confirmar`);
    if (summary.unmatched) parts.push(`${summary.unmatched} sense nota (es deixen com estan)`);
    matchSummary.innerHTML = parts.join(" · ");

    fillWarnings.innerHTML = result.warnings
      .map((warning) => `<div class="alert warning">${escapeHtml(warning)}</div>`)
      .join("");

    const studentOptions = grades.student_rows.map((row) => [row, grades.rows[row][grades.name_column]]);
    matchBody.innerHTML = result.participants
      .map((participant) => {
        const selected = participant.student_row ?? NO_STUDENT;
        const options = [option(NO_STUDENT, "— Sense nota —", selected === NO_STUDENT)]
          .concat(studentOptions.map(([row, name]) => option(row, name, row === selected)))
          .join("");
        const confirm = participant.status === "probable"
          ? `<button type="button" class="link-button" data-confirm="${escapeHtml(participant.identifier)}" data-row="${participant.student_row}">Confirma</button>`
          : "";
        const warnings = participant.warnings
          .map((warning) => `<small class="row-warning">${escapeHtml(warning)}</small>`)
          .join("");
        return `<tr class="status-${participant.status}">
          <td>${escapeHtml(participant.fullname)}${warnings}</td>
          <td><select data-identifier="${escapeHtml(participant.identifier)}" aria-label="Estudiant per a ${escapeHtml(participant.fullname)}">${options}</select></td>
          <td class="grade-cell">${escapeHtml(participant.grade)}</td>
          <td><span class="status status-badge-${participant.status}">${STATUS_LABELS[participant.status]}</span>${confirm}</td>
        </tr>`;
      })
      .join("");

    unusedStudents.innerHTML = result.unused.length
      ? `<p class="unused-title">Estudiants de les notes finals sense participant al Moodle (${result.unused.length}):</p>
         <div class="upload-list">${result.unused.map((student) => `<span class="upload-chip muted-chip">${escapeHtml(student.name)}</span>`).join("")}</div>`
      : "";
  }

  function render() {
    renderWorksheetStatus();
    renderGradesFileStatus();
    const result = state.result;
    const grades = result && result.grades;
    review.hidden = !grades;
    if (grades) {
      renderSettings(grades);
      renderSheetPreview(grades);
      feedbackSample.innerHTML = result.feedback_sample || '<p class="upload-placeholder">Cap columna seleccionada.</p>';
      renderMatches(result);
    }
    downloadButton.disabled = !(result && result.summary && result.summary.applied > 0);
  }

  // --- Inputs ---------------------------------------------------------------

  function resetGradeChoices() {
    state.options = emptyOptions();
    state.matches = {};
  }

  function bindUploadZone(zone, input) {
    zone.addEventListener("click", () => input.click());
    zone.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        input.click();
      }
    });
  }

  bindUploadZone(worksheetZone, worksheetInput);
  bindUploadZone(gradesZone, gradesFileInput);

  worksheetInput.addEventListener("change", () => {
    state.worksheet = worksheetInput.files[0] || null;
    state.matches = {};
    worksheetInput.value = "";
    schedulePreview();
  });

  gradesFileInput.addEventListener("change", () => {
    state.gradesFile = gradesFileInput.files[0] || null;
    gradesFileInput.value = "";
    resetGradeChoices();
    schedulePreview();
  });

  gradesText.addEventListener("input", () => {
    resetGradeChoices();
    schedulePreview(400);
  });

  for (const segment of segments) {
    segment.addEventListener("click", () => {
      state.source = segment.dataset.source;
      for (const other of segments) {
        const isActive = other === segment;
        other.classList.toggle("is-active", isActive);
        other.setAttribute("aria-pressed", String(isActive));
      }
      pasteBlock.hidden = state.source !== "paste";
      fileBlock.hidden = state.source !== "file";
      resetGradeChoices();
      schedulePreview();
    });
  }

  headerRowSelect.addEventListener("change", () => {
    // A different header row changes every column, so the other choices are
    // detected again.
    resetGradeChoices();
    state.options.header_row = Number(headerRowSelect.value);
    schedulePreview();
  });

  nameColumnSelect.addEventListener("change", () => {
    state.options.name_column = Number(nameColumnSelect.value);
    state.options.feedback_columns = null;
    state.matches = {};
    schedulePreview();
  });

  gradeColumnSelect.addEventListener("change", () => {
    state.options.grade_column = Number(gradeColumnSelect.value);
    schedulePreview();
  });

  layoutSelect.addEventListener("change", () => {
    state.options.layout = layoutSelect.value;
    schedulePreview();
  });

  feedbackColumns.addEventListener("change", () => {
    state.options.feedback_columns = Array.from(feedbackColumns.querySelectorAll("input:checked")).map((input) => Number(input.value));
    schedulePreview();
  });

  matchBody.addEventListener("change", (event) => {
    const select = event.target.closest("select[data-identifier]");
    if (select) {
      state.matches[select.dataset.identifier] = Number(select.value);
      schedulePreview();
    }
  });

  matchBody.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-confirm]");
    if (button) {
      state.matches[button.dataset.confirm] = Number(button.dataset.row);
      schedulePreview();
    }
  });

  downloadButton.addEventListener("click", download);
  render();
})();
