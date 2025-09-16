// These should all be run from the EA model instance you want to change

// %-------- .js Script to compare original to current model and write a csv of differences ---------%
function out(s){ Repository.EnsureOutputVisible("Script"); Session.Output(String(s)); }
function parse(xml){ var d=new ActiveXObject("MSXML2.DOMDocument"); d.async=false; d.loadXML(xml);
  var rs=d.selectNodes("//Row"), a=[]; for (var i=0;i<rs.length;i++){ var o={}, cs=rs[i].childNodes;
  for (var j=0;j<cs.length;j++) o[cs[j].nodeName]=cs[j].text; a.push(o);} return a; }

function main(){
  var OLD_FILE = "X:\\\\Research\\\\Ravens\\\\network copy\\\\cim\\\\original\\\\iec61970cim17v40_iec61968cim13v13b_iec62325cim03v17b_CIM100.1.1.1.eap";
  var CSV_OUT  = "X:\\\\Research\\\\Ravens\\\\network copy\\\\cim\\\\original\\\\all_connectors_with_old_color.csv";

  var oldRepo = new ActiveXObject("EA.Repository");
  oldRepo.OpenFile(OLD_FILE);
  var oldRows = parse(oldRepo.SQLQuery("SELECT Connector_ID, ea_guid, LineColor FROM t_connector"));
  var oldColorByGuid = {};
  for (var i=0;i<oldRows.length;i++){
    var g = oldRows[i].ea_guid; if (!g) continue;
    var c = parseInt(oldRows[i].LineColor,10); if (isNaN(c)) c = -1;
    oldColorByGuid[g] = c;
  }
  try{ oldRepo.CloseFile(); oldRepo.Exit(); }catch(e){}

  var curRows = parse(Repository.SQLQuery("SELECT Connector_ID, ea_guid, LineColor FROM t_connector"));

  var fso = new ActiveXObject("Scripting.FileSystemObject");
  var f   = fso.CreateTextFile(CSV_OUT, true);
  f.WriteLine("ea_guid,new_connector_id,new_color,old_color");
  for (var k=0;k<curRows.length;k++){
    var guid = curRows[k].ea_guid;
    var id   = parseInt(curRows[k].Connector_ID,10);
    var newC = parseInt(curRows[k].LineColor,10); if (isNaN(newC)) newC = -1;
    var oldC = (oldColorByGuid.hasOwnProperty(guid) ? oldColorByGuid[guid] : "");
    f.WriteLine(guid + "," + id + "," + newC + "," + oldC);
  }
  f.Close();
  out("CSV written: " + CSV_OUT);
}
main();

# %-------- Overwrites colors to set back to default values; also resets ravens-only connectors to default color ---------%
function out(s){ Repository.EnsureOutputVisible("Script"); Session.Output(String(s)); }

// --- CSV -> apply model-level colors (t_connector) and collect IDs to clear on diagrams
function applyModelColorsFromCSV(csvPath){
  var fso = new ActiveXObject("Scripting.FileSystemObject");
  if (!fso.FileExists(csvPath)) { out("ERROR: CSV not found: " + csvPath); return []; }
  var f = fso.OpenTextFile(csvPath, 1, false); // ForReading

  var header = true, rows=0, setOld=0, setDefault=0, errs=0;
  var idSet = {}; // map for quick lookup
  while(!f.AtEndOfStream){
    var line = f.ReadLine();
    if (header){ header=false; continue; }
    if (!line) continue;

    // CSV: ea_guid,new_connector_id,new_color,old_color
    var p = line.split(",");
    if (p.length < 4) continue;

    var id = parseInt(p[1], 10);
    if (isNaN(id)) continue;

    var oldColorStr = p[3];
    var target = (oldColorStr === "" ? -1 : parseInt(oldColorStr, 10));
    if (isNaN(target)) target = -1;

    try {
      Repository.Execute("UPDATE t_connector SET LineColor = " + target + " WHERE Connector_ID = " + id);
      idSet[id] = true;
      if (target === -1) setDefault++; else setOld++;
      rows++;
    } catch(e){
      errs++;
      // out("WARN id="+id+": "+e.description);
    }
  }
  f.Close();
  out("Model colors set. rows="+rows+" | set-old="+setOld+" | set-default="+setDefault+" | errors="+errs);
  return idSet;
}

// --- Clear per-diagram overrides via EA API (no SQL, no pop-ups)
function clearDiagramOverridesForIDs(idSet){
  var cleared = 0, diagramsVisited = 0;

  function clearInDiagram(diag){
    var links = diag.DiagramLinks; if (!links) return 0;
    var localCleared = 0;
    for (var i=0; i<links.Count; i++){
      var dl = links.GetAt(i);
      if (idSet[dl.ConnectorID]){
        // Set override to default
        dl.LineColor = -1;
        dl.Update();
        localCleared++;
      }
    }
    // Persist diagram changes
    if (localCleared > 0){
      diag.Update();
      // Reloading once at end is enough; we skip per-diagram reload to go faster.
    }
    return localCleared;
  }

  function walkPackage(pkg){
    // clear on diagrams in this package
    for (var i=0; i<pkg.Diagrams.Count; i++){
      var d = pkg.Diagrams.GetAt(i);
      diagramsVisited++;
      cleared += clearInDiagram(d);
    }
    // recurse
    for (var j=0; j<pkg.Packages.Count; j++){
      walkPackage(pkg.Packages.GetAt(j));
    }
  }

  // walk all models
  var models = Repository.Models;
  for (var m=0; m<models.Count; m++){
    walkPackage(models.GetAt(m));
  }

  out("Diagram overrides cleared: " + cleared + " (diagrams visited: " + diagramsVisited + ")");
}

function main(){
  var CSV_IN = "X:\\\\Research\\\\Ravens\\\\network copy\\\\cim\\\\original\\\\all_connectors_with_old_color.csv";
  out("Resetting connector colors from CSV (model-level) and clearing diagram overrides via API…");

  var idSet = applyModelColorsFromCSV(CSV_IN);
  clearDiagramOverridesForIDs(idSet);

  // One refresh at the end
  Repository.RefreshOpenDiagrams(true);
  var d = Repository.GetCurrentDiagram();
  if (d) Repository.ReloadDiagram(d.DiagramID);

  out("Done.");
}
main();


// %-------- Reset all the RAVENS linewidths to default ---------%
function out(s){ Repository.EnsureOutputVisible("Script"); Session.Output(String(s)); }

// find the first package named exactly "RAVENS"
function findPackageByName(name){
  for (var m=0; m<Repository.Models.Count; m++){
    var p = findInPkg(Repository.Models.GetAt(m), name);
    if (p) return p;
  }
  return null;

  function findInPkg(pkg, name){
    if (pkg.Name === name) return pkg;
    for (var i=0; i<pkg.Packages.Count; i++){
      var hit = findInPkg(pkg.Packages.GetAt(i), name);
      if (hit) return hit;
    }
    return null;
  }
}

function resetLineWidthsUnderPackage(pkgName, defaultWidth){
  var pkg = findPackageByName(pkgName);
  if (!pkg){ out("Package not found: " + pkgName); return; }

  var diagramsVisited = 0, linksTouched = 0;

  function doDiagram(diag){
    var changed = false;
    var links = diag.DiagramLinks;
    for (var i=0; i<links.Count; i++){
      var dl = links.GetAt(i);
      var cur = parseInt(dl.LineWidth, 10) || 0;
      if (cur !== defaultWidth){
        dl.LineWidth = defaultWidth;   // EA's normal default is 1
        dl.Update();
        changed = true;
        linksTouched++;
      }
    }
    if (changed) diag.Update();
  }

  function walk(pkg){
    for (var d=0; d<pkg.Diagrams.Count; d++){
      doDiagram(pkg.Diagrams.GetAt(d));
      diagramsVisited++;
    }
    for (var i=0; i<pkg.Packages.Count; i++){
      walk(pkg.Packages.GetAt(i));
    }
  }

  walk(pkg);

  out("Package: " + pkgName + " | diagrams visited: " + diagramsVisited + " | links reset: " + linksTouched);
  Repository.RefreshOpenDiagrams(true);
  var cur = Repository.GetCurrentDiagram(); if (cur) Repository.ReloadDiagram(cur.DiagramID);
}

function main(){
  resetLineWidthsUnderPackage("RAVENS", 1); // set to 1 = default
}
main();




// === Tag RAVENS connectors from CSV new_color ===
function out(s){ Repository.EnsureOutputVisible("Script"); Session.Output(String(s)); }

// --- read CSV into: id -> new_color (int)
function readNewColorsMap(csvPath){
  var fso = new ActiveXObject("Scripting.FileSystemObject");
  if (!fso.FileExists(csvPath)){ out("ERROR: CSV not found: " + csvPath); return {}; }
  var f = fso.OpenTextFile(csvPath, 1, false); // ForReading
  var map = {};
  var header = true;
  while(!f.AtEndOfStream){
    var line = f.ReadLine();
    if (header){ header=false; continue; }
    if (!line) continue;
    // CSV: ea_guid,new_connector_id,new_color,old_color
    var p = line.split(",");
    if (p.length < 3) continue;
    var id = parseInt(p[1], 10);
    var newc = (p[2] === "" ? NaN : parseInt(p[2], 10));
    if (!isNaN(id) && !isNaN(newc)) map[id] = newc;
  }
  f.Close();
  return map;
}

// --- find first package named exactly name
function findPackageByName(name){
  var m, p;
  for (m=0; m<Repository.Models.Count; m++){
    p = findInPkg(Repository.Models.GetAt(m), name);
    if (p) return p;
  }
  return null;
  function findInPkg(pkg, nm){
    if (pkg.Name == nm) return pkg;
    for (var i=0; i<pkg.Packages.Count; i++){
      var hit = findInPkg(pkg.Packages.GetAt(i), nm);
      if (hit) return hit;
    }
    return null;
  }
}

// --- collect ConnectorIDs that appear on diagrams under a package tree
function collectConnectorIDsUnderPackage(pkg){
  var set = {};
  function walk(p){
    var i, j;
    for (i=0; i<p.Diagrams.Count; i++){
      var d = p.Diagrams.GetAt(i);
      var links = d.DiagramLinks;
      for (j=0; j<links.Count; j++){
        set[ links.GetAt(j).ConnectorID ] = true;
      }
    }
    for (i=0; i<p.Packages.Count; i++) walk(p.Packages.GetAt(i));
  }
  walk(pkg);
  return set;
}

// --- classify role from the prior new_color
function roleForColor(c){
  // 128 & 2763429 → referenceConnector (red-ish); 5737262 → embeddedConnector (green)
  if (c === 128 || c === 2763429) return "referenceConnector";
  if (c === 5737262) return "embeddedConnector";
  return null;
}

function main(){
  // set your CSV path
  var CSV_IN = "X:\\\\Research\\\\Ravens\\\\network copy\\\\cim\\\\original\\\\all_connectors_with_old_color.csv";
  var TARGET_PACKAGE = "RAVENS";

  out("Tagging from CSV new_color, package: " + TARGET_PACKAGE);

  var pkg = findPackageByName(TARGET_PACKAGE);
  if (!pkg){ out("ERROR: package not found: " + TARGET_PACKAGE); return; }

  // connectors that actually appear on RAVENS diagrams
  var idSet = collectConnectorIDsUnderPackage(pkg);
  var ids = [];
  for (var k in idSet){ if (idSet[k] === true) ids.push(parseInt(k,10)); }
  out("Connectors on RAVENS diagrams: " + ids.length);

  // map of connector_id -> prior new_color
  var newColorMap = readNewColorsMap(CSV_IN);

  var tagged=0, already=0, skipped=0, missing=0;

  for (var i=0; i<ids.length; i++){
    var cid = ids[i];
    var prior = newColorMap.hasOwnProperty(cid) ? newColorMap[cid] : NaN;
    if (isNaN(prior)){ skipped++; continue; } // not in CSV → no role

    var role = roleForColor(prior);
    if (!role){ skipped++; continue; }        // color not in our mapping → ignore

    var con = Repository.GetConnectorByID(cid);
    if (!con){ missing++; continue; }

    try{
      var tvc = con.TaggedValues;

      // remove legacy tag if present
      var t;
      for (t = tvc.Count - 1; t >= 0; t--){
        var tvOld = tvc.GetAt(t);
        if (tvOld.Name == "ravens_color") tvc.DeleteAt(t, true);
      }
      tvc.Refresh();

      // upsert ravensRole
      var found = false;
      for (t = 0; t < tvc.Count; t++){
        var tv = tvc.GetAt(t);
        if (tv.Name == "ravensRole"){
          found = true;
          if (tv.Value != role){
            tv.Value = role;
            tv.Update();
            con.Update();
            tagged++;
          } else {
            already++;
          }
          break;
        }
      }
      if (!found){
        var newTV = tvc.AddNew("ravensRole", role);
        newTV.Update();
        tvc.Refresh();
        con.Update();
        tagged++;
      }
    }catch(e){
      // uncomment to debug individual issues:
      // out("WARN cid="+cid+": " + e.description);
      skipped++;
    }
  }

  out("Set/updated: " + tagged + " | already correct: " + already + " | skipped (no CSV/new_color or unmapped color): " + skipped + " | missing connectors: " + missing);

  Repository.RefreshOpenDiagrams(true);
  var d = Repository.GetCurrentDiagram(); if (d) Repository.ReloadDiagram(d.DiagramID);
  out("Done.");
}

main();






// Copy legend from diagram "Faults" to all diagrams under package "RAVENS" (EA JScript)
function out(s){ Repository.EnsureOutputVisible("Script"); Session.Output(String(s)); }

// Find a diagram by exact name across the model
function findDiagramByName(name){
  for (var m=0; m<Repository.Models.Count; m++){
    var d = findInPkg(Repository.Models.GetAt(m), name);
    if (d) return d;
  }
  return null;
  function findInPkg(pkg, nm){
    for (var i=0; i<pkg.Diagrams.Count; i++){
      var dg = pkg.Diagrams.GetAt(i);
      if (dg.Name == nm) return dg;
    }
    for (var j=0; j<pkg.Packages.Count; j++){
      var hit = findInPkg(pkg.Packages.GetAt(j), nm);
      if (hit) return hit;
    }
    return null;
  }
}

// Find package by exact name
function findPackageByName(name){
  for (var m=0; m<Repository.Models.Count; m++){
    var p = dfs(Repository.Models.GetAt(m), name);
    if (p) return p;
  }
  return null;
  function dfs(pkg, nm){
    if (pkg.Name == nm) return pkg;
    for (var i=0; i<pkg.Packages.Count; i++){
      var hit = dfs(pkg.Packages.GetAt(i), nm);
      if (hit) return hit;
    }
    return null;
  }
}

// Legend detector: looks for "legend" token in DiagramObject.Style (fallback: element.StyleEx)
function isLegendDiagramObject(dobj){
  var st = String(dobj.Style||"").toLowerCase();
  if (st.indexOf("legend") >= 0) return true;
  try {
    var el = Repository.GetElementByID(dobj.ElementID);
    var esx = el ? String(el.StyleEx||"").toLowerCase() : "";
    if (esx.indexOf("legend") >= 0) return true;
  } catch(e){}
  return false;
}

// Grab template (style + position) from the first legend on "Faults"
function getLegendTemplateFromDiagram(diag){
  var dos = diag.DiagramObjects;
  for (var i=0; i<dos.Count; i++){
    var dobj = dos.GetAt(i);
    if (isLegendDiagramObject(dobj)){
      return {
        style:    String(dobj.Style||""),                           // << use Style
        geometry: String(dobj.Geometry||"l=40;t=40;r=260;b=140;")
      };
    }
  }
  return null;
}

// Ensure a legend exists on 'diag' that matches 'template'
function ensureLegendOnDiagram(diag, template){
  var dos = diag.DiagramObjects;

  // Update existing legend
  for (var i=0; i<dos.Count; i++){
    var dobj = dos.GetAt(i);
    if (isLegendDiagramObject(dobj)){
      dobj.Style = template.style;             // << write Style
      // keep existing position; to force position, uncomment:
      // dobj.Geometry = template.geometry;
      dobj.Update();
      return "updated";
    }
  }

  // Create diagram-only legend object with the template style
  try {
    var newDO = dos.AddNew(template.geometry, ""); // no backing element
    newDO.Style = template.style;                  // << write Style
    newDO.Update();
    dos.Refresh();
    return "created";
  } catch(e){
    // Fallback: create a small Text element, then place it
    try {
      var pkg = Repository.GetPackageByID(diag.PackageID);
      var el = pkg.Elements.AddNew("", "Text");
      el.Update(); pkg.Elements.Refresh();
      var do2 = dos.AddNew(template.geometry, ""+el.ElementID);
      do2.Style = template.style;                 // << write Style
      do2.Update(); dos.Refresh();
      return "created";
    } catch(e2){
      return "failed";
    }
  }
}

// Iterate all diagrams under a package
function forEachDiagramUnderPackage(pkg, fn){
  (function walk(p){
    for (var i=0; i<p.Diagrams.Count; i++) fn(p.Diagrams.GetAt(i));
    for (var j=0; j<p.Packages.Count; j++) walk(p.Packages.GetAt(j));
  })(pkg);
}

function main(){
  var TEMPLATE_DIAGRAM_NAME = "Faults";
  var TARGET_PACKAGE_NAME   = "RAVENS";

  out("Using legend from diagram: " + TEMPLATE_DIAGRAM_NAME);
  var tmplDiag = findDiagramByName(TEMPLATE_DIAGRAM_NAME);
  if (!tmplDiag){ out("ERROR: diagram not found: " + TEMPLATE_DIAGRAM_NAME); return; }

  var template = getLegendTemplateFromDiagram(tmplDiag);
  if (!template){ out("ERROR: no legend found on '" + TEMPLATE_DIAGRAM_NAME + "'."); return; }
  out("Template legend captured.");

  var pkg = findPackageByName(TARGET_PACKAGE_NAME);
  if (!pkg){ out("ERROR: package not found: " + TARGET_PACKAGE_NAME); return; }

  var total=0, updated=0, created=0, failed=0;
  forEachDiagramUnderPackage(pkg, function(diag){
    total++;
    var res = ensureLegendOnDiagram(diag, template);
    if (res == "updated") { updated++; diag.Update(); }
    else if (res == "created") { created++; diag.Update(); }
    else { failed++; }
  });

  Repository.RefreshOpenDiagrams(true);
  var cur = Repository.GetCurrentDiagram(); if (cur) Repository.ReloadDiagram(cur.DiagramID);

  out("Done. Diagrams scanned: " + total + " | legends updated: " + updated + " | created: " + created + " | failed: " + failed);
}

main();
