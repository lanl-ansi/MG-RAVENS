!INC Local Scripts.EAConstants-JScript

(function () {
  // ---------------- config ----------------
  var TAG_NAME  = "ravensRole";

  // Allowed roles (update to your dictionary)
  var ALLOWED = {
    "pink":1, "rootclass":1, "compoundclass":1,
    "yellowclass":1, "embeddedclass":1, "white":1,
    "containerclass":1, "substitutableclass":1, "inheritonlyclass":1
  };

  var ELEMENTS_CSV = "X:\\Research\\Ravens\\ravensRole_updates.csv";      // Input: Object_ID,ravensRole
  var OUTPUT_CSV   = "X:\\Research\\Ravens\\element_roles_applied.csv";   // Output log
  var DRY_RUN = false;                       // first run = true (log only). set false to apply.
  var SKIP_IF_NOT_YELLOW_OR_BLANK = true;   // set false if you want to overwrite anything

  // ---------------- compat helpers (EA JScript lacks String.trim) ----------------
  function trimStr(s){ return String(s==null?"":s).replace(/^\s+|\s+$/g,""); }
  function lowerStr(s){ return trimStr(s).toLowerCase(); }

  // ---------------- output helpers ----------------
  function outInit() {
    Repository.CreateOutputTab("RAVENS");
    Repository.ClearOutput("RAVENS");
    Repository.EnsureOutputVisible("RAVENS");
  }
  function log(msg) { Repository.WriteOutput("RAVENS", String(msg), 0); }

  // ---------------- IO (UTF-8 safe) ----------------
  function readAllText(path) {
    var fso = new ActiveXObject("Scripting.FileSystemObject");
    if (!fso.FileExists(path)) { throw new Error("Input file not found: " + path); }
    var st = new ActiveXObject("ADODB.Stream");
    st.Type = 2;           // adTypeText
    st.Charset = "utf-8";
    st.Open();
    st.LoadFromFile(path);
    var txt = st.ReadText(-1); // adReadAll
    st.Close();
    // normalize newlines & strip BOM
    return String(txt).replace(/\uFEFF/g, "").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  }

  function writeAllText(path, text) {
    var st = new ActiveXObject("ADODB.Stream");
    st.Type = 2;           // adTypeText
    st.Charset = "utf-8";
    st.Open();
    st.WriteText(String(text), 0);
    st.SaveToFile(path, 2); // adSaveCreateOverWrite
    st.Close();
  }

  // ---------------- CSV parsing ----------------
  // expects two columns: Object_ID,ravensRole (header optional). no embedded commas.
  function parseSimpleCSVTwoCols(csvText) {
    var lines = String(csvText||"").split("\n");
    var out = [], headerDone = false;
    for (var i=0; i<lines.length; i++) {
      var line = lines[i];
      if (!line) continue;
      line = trimStr(line);
      if (!line || line.charAt(0) === "#") continue;

      var parts = line.split(",");
      if (parts.length < 2) continue;

      if (!headerDone) {
        var a = lowerStr(parts[0].replace(/^"|"$/g,""));
        var b = lowerStr(parts[1].replace(/^"|"$/g,""));
        if (a.indexOf("object_id") !== -1 || b.indexOf("ravensrole") !== -1) {
          headerDone = true; continue;
        }
        headerDone = true; // treat first row as data
      }

      var idStr = trimStr(parts[0].replace(/^"|"$/g,""));
      var role  = trimStr(parts[1].replace(/^"|"$/g,""));
      var id = parseInt(idStr, 10);
      if (!isNaN(id) && role) out.push([id, role]);
    }
    return out;
  }

  // ---------------- tagged value helpers (elements only) ----------------
  function findElementTV(elem, name) {
    var lname = lowerStr(name);
    for (var i=0; i<elem.TaggedValues.Count; i++) {
      var tv = elem.TaggedValues.GetAt(i);
      if (tv.Name && lowerStr(tv.Name) === lname) return tv;
    }
    return null;
  }
  function getOrCreateElementTV(elem, name) {
    var tv = findElementTV(elem, name);
    if (tv) return tv;
    var newTv = elem.TaggedValues.AddNew(name, "");
    newTv.Update();
    elem.TaggedValues.Refresh();
    return newTv;
  }

  // ---------------- core update (elements only) ----------------
  function planOrUpdateElementRole(objectId, newRoleRaw) {
    var row = { Object_ID: objectId, Name: "", Prev: "", New: newRoleRaw, Status: "", Note: "" };

    try {
      var newRole = trimStr(newRoleRaw);
      var newRoleLC = lowerStr(newRole);
      if (!ALLOWED[newRoleLC]) { row.Status="skip"; row.Note="role_not_allowed"; return row; }

      var elem = Repository.GetElementByID(objectId);
      if (!elem) { row.Status="error"; row.Note="element_not_found"; return row; }
      row.Name = elem.Name;

      var tv = findElementTV(elem, TAG_NAME);
      var prev = tv ? trimStr(tv.Value || "") : "";
      row.Prev = prev;

      if (SKIP_IF_NOT_YELLOW_OR_BLANK) {
        var prevLC = lowerStr(prev);
        if (prev && prevLC !== "yellowclass") {
          row.Status = "skip"; row.Note = "prev_not_blank_or_yellowClass"; return row;
        }
      }

      if (prev === newRole) { row.Status="unchanged"; return row; }

      if (DRY_RUN) {
        row.Status = "would_update";
      } else {
        var tv2 = tv || getOrCreateElementTV(elem, TAG_NAME);
        tv2.Value = newRole;
        tv2.Update();
        elem.TaggedValues.Refresh();
        elem.Update();
        row.Status = "updated";
      }
      return row;

    } catch (e) {
      row.Status = "error"; row.Note = (e && (e.message || e.description)) ? (e.message || e.description) : "exception";
      return row;
    }
  }

  function runElementsFromCSV(pathIn, pathOut) {
    outInit();
    var csv;
    try {
      csv = readAllText(pathIn);
      log("OK: read CSV (" + csv.length + " chars): " + pathIn);
    } catch (e) {
      log("ERROR reading CSV: " + (e.message || e.description));
      return;
    }

    var pairs = parseSimpleCSVTwoCols(csv);
    log("Rows parsed: " + pairs.length);

    var results = [];
    var counts = { updated:0, would_update:0, unchanged:0, skip:0, error:0 };

    for (var i=0; i<pairs.length; i++) {
      var objectId = pairs[i][0], role = pairs[i][1];
      var r = planOrUpdateElementRole(objectId, role);
      results.push(r);
      counts[r.Status] = (counts[r.Status] || 0) + 1;
      log(r.Status.toUpperCase()+": " + r.Object_ID + " [" + (r.Name||"") + "] " +
          r.Prev + " -> " + r.New + (r.Note ? (" ("+r.Note+")") : ""));
    }

    var lines = [];
    lines.push("Object_ID,Name,Prev,New,Status,Note");
    for (var j=0; j<results.length; j++) {
      var rr = results[j];
      function esc(s){ return ('"'+String(s||"").replace(/"/g,'""')+'"'); }
      lines.push([rr.Object_ID, esc(rr.Name), esc(rr.Prev), esc(rr.New), rr.Status, esc(rr.Note)].join(","));
    }
    writeAllText(pathOut, lines.join("\r\n"));

    log("Done. DRY_RUN="+DRY_RUN+
        ". updated="+counts.updated+
        ", would_update="+counts.would_update+
        ", unchanged="+counts.unchanged+
        ", skip="+counts.skip+
        ", error="+counts.error);
    log("Audit CSV written: " + pathOut);
  }

  // --------- run ----------
  runElementsFromCSV(ELEMENTS_CSV, OUTPUT_CSV);
})();
