// These should all be run from the EA model instance you want to change

// %---- Generates a csv of objects/elements for "original" CIM and existing model ----%
function out(s){ Repository.EnsureOutputVisible("Script"); Session.Output(String(s)); }

// Read BCol from DiagramObject.Style (returns int or -1 if none)
function getBCol(style){
  var s = String(style||"");
  var parts = s.split(";");
  for (var i=0;i<parts.length;i++){
    var p = parts[i];
    var eq = p.indexOf("=");
    if (eq>0){
      var k = p.substring(0,eq), v = p.substring(eq+1);
      if (k=="BCol"){
        var n = parseInt(v,10);
        if (!isNaN(n) && n>0) return n;
      }
    }
  }
  return -1; // default
}

// walk all diagrams in a repo, count modal BCol per element GUID
function modalBColByGUID_allDiagrams(repo){
  var counts = {}; // guid -> { bcol:int -> freq }
  function bump(g,w){
    if (!counts[g]) counts[g] = {};
    counts[g][w] = (counts[g][w]||0)+1;
  }
  function walkPkg(pkg){
    for (var i=0;i<pkg.Diagrams.Count;i++){
      var d = pkg.Diagrams.GetAt(i);
      var dos = d.DiagramObjects;
      for (var j=0;j<dos.Count;j++){
        var dob = dos.GetAt(j);
        var el  = repo.GetElementByID(dob.ElementID);
        if (!el) continue;
        var guid = el.ElementGUID;
        var bc = getBCol(dob.Style);
        if (bc>0) bump(guid, bc);
      }
    }
    for (var k=0;k<pkg.Packages.Count;k++) walkPkg(pkg.Packages.GetAt(k));
  }
  for (var m=0;m<repo.Models.Count;m++) walkPkg(repo.Models.GetAt(m));

  var modal = {}; // guid -> modal bcol (int)
  for (var g in counts){
    if (!counts.hasOwnProperty(g)) continue;
    var bag = counts[g], bestW=-1, bestN=-1;
    for (var w in bag){
      if (!bag.hasOwnProperty(w)) continue;
      var n = bag[w];
      if (n>bestN){ bestN=n; bestW=parseInt(w,10); }
    }
    if (bestW>0) modal[g]=bestW;
  }
  return modal;
}

// find package by exact name
function findPackageByName(name){
  function dfs(pkg){
    if (pkg.Name==name) return pkg;
    for (var i=0;i<pkg.Packages.Count;i++){ var hit=dfs(pkg.Packages.GetAt(i)); if (hit) return hit; }
    return null;
  }
  for (var m=0;m<Repository.Models.Count;m++){ var p=dfs(Repository.Models.GetAt(m)); if (p) return p; }
  return null;
}

// modal BCol by GUID but only considering DIAGRAMS under a given package in current repo
function modalBColByGUID_underPackage(pkg){
  var counts = {};
  function bump(g,w){
    if (!counts[g]) counts[g] = {};
    counts[g][w] = (counts[g][w]||0)+1;
  }
  function walk(p){
    for (var i=0;i<p.Diagrams.Count;i++){
      var d = p.Diagrams.GetAt(i);
      var dos = d.DiagramObjects;
      for (var j=0;j<dos.Count;j++){
        var dob = dos.GetAt(j);
        var el  = Repository.GetElementByID(dob.ElementID);
        if (!el) continue;
        var guid = el.ElementGUID;
        var bc = getBCol(dob.Style);
        if (bc>0) bump(guid, bc);
      }
    }
    for (var k=0;k<p.Packages.Count;k++) walk(p.Packages.GetAt(k));
  }
  walk(pkg);

  var modal = {};
  for (var g in counts){
    if (!counts.hasOwnProperty(g)) continue;
    var bag = counts[g], bestW=-1, bestN=-1;
    for (var w in bag){
      if (!bag.hasOwnProperty(w)) continue;
      var n = bag[w];
      if (n>bestN){ bestN=n; bestW=parseInt(w,10); }
    }
    if (bestW>0) modal[g]=bestW;
  }
  return modal;
}

function main(){
  // set paths
  var OLD_FILE = "X:\\\\Research\\\\Ravens\\\\network copy\\\\cim\\\\original\\\\iec61970cim17v40_iec61968cim13v13b_iec62325cim03v17b_CIM100.1.1.1.eap";
  var CSV_OUT  = "X:\\\\Research\\\\Ravens\\\\network copy\\\\cim\\\\original\\\\ravens_elements_colors.csv";
  var TARGET_PACKAGE = "RAVENS";

  out("Exporting RAVENS element colors (new vs old) …");

  var pkg = findPackageByName(TARGET_PACKAGE);
  if (!pkg){ out("ERROR: package not found: "+TARGET_PACKAGE); return; }

  // NEW: modal BCol on diagrams under RAVENS
  var newModal = modalBColByGUID_underPackage(pkg);

  // OLD: modal BCol across all diagrams
  var old = new ActiveXObject("EA.Repository");
  try{ old.OpenFile(OLD_FILE); }catch(e){ out("ERROR opening old repo: "+e.description); return; }
  var oldModal = modalBColByGUID_allDiagrams(old);
  try{ old.CloseFile(); old.Exit(); }catch(e){}

  // write CSV (only elements seen on RAVENS diagrams in NEW)
  var fso = new ActiveXObject("Scripting.FileSystemObject");
  var f   = fso.CreateTextFile(CSV_OUT, true);
  f.WriteLine("ea_guid,element_id,new_bcol,old_bcol");

  var written=0;
  for (var guid in newModal){
    if (!newModal.hasOwnProperty(guid)) continue;
    // resolve element_id once (for convenience)
    var el = Repository.GetElementByGUID(guid);
    var eid = el ? el.ElementID : "";
    var nb  = newModal[guid];
    var ob  = oldModal.hasOwnProperty(guid) ? oldModal[guid] : "";
    f.WriteLine(guid + "," + eid + "," + nb + "," + ob);
    written++;
  }
  f.Close();

  out("CSV written: " + CSV_OUT + " (rows: "+written+")");
}
main();




// %------- Resets object colors to match CIM ------%
function out(s){ Repository.EnsureOutputVisible("Script"); Session.Output(String(s)); }

function setOrClearBCol(style, target){
  var s = String(style||"");
  var parts = s ? s.split(";") : [];
  var found = false, i, outParts=[];
  for (i=0;i<parts.length;i++){
    if (!parts[i]) continue;
    var eq = parts[i].indexOf("="); if (eq<=0) { outParts.push(parts[i]); continue; }
    var k = parts[i].substring(0,eq), v = parts[i].substring(eq+1);
    if (k=="BCol"){
      found = true;
      if (target>0) outParts.push("BCol="+target); // replace
      // else drop it to clear
    } else {
      outParts.push(parts[i]);
    }
  }
  if (!found && target>0) outParts.push("BCol="+target);
  return outParts.join(";") + (outParts.length?";":"");
}

function findPackageByName(name){
  function dfs(pkg){
    if (pkg.Name==name) return pkg;
    for (var i=0;i<pkg.Packages.Count;i++){ var hit=dfs(pkg.Packages.GetAt(i)); if (hit) return hit; }
    return null;
  }
  for (var m=0;m<Repository.Models.Count;m++){ var p=dfs(Repository.Models.GetAt(m)); if (p) return p; }
  return null;
}

function readCsvMap(csvPath){
  // returns guid -> {old:int or NaN, new:int or NaN}
  var fso = new ActiveXObject("Scripting.FileSystemObject");
  if (!fso.FileExists(csvPath)){ out("ERROR: CSV not found: "+csvPath); return {}; }
  var f = fso.OpenTextFile(csvPath, 1, false);
  var map = {}, header=true;
  while(!f.AtEndOfStream){
    var line = f.ReadLine();
    if (header){ header=false; continue; }
    if (!line) continue;
    var p = line.split(",");
    if (p.length<4) continue;
    var g = p[0];
    var nb = (p[2]==""?NaN:parseInt(p[2],10));
    var ob = (p[3]==""?NaN:parseInt(p[3],10));
    map[g] = { new_bcol: nb, old_bcol: ob };
  }
  f.Close();
  return map;
}

function main(){
  var CSV_IN = "X:\\\\Research\\\\Ravens\\\\network copy\\\\cim\\\\original\\\\ravens_elements_colors.csv";
  var TARGET_PACKAGE = "RAVENS";

  out("Resetting RAVENS diagram element colors to OLD/default …");

  var pkg = findPackageByName(TARGET_PACKAGE);
  if (!pkg){ out("ERROR: package not found: "+TARGET_PACKAGE); return; }

  var infoByGuid = readCsvMap(CSV_IN);

  var diagrams=0, touched=0;
  (function walk(p){
    for (var i=0;i<p.Diagrams.Count;i++){
      var d = p.Diagrams.GetAt(i);
      var changed=false;
      var dos = d.DiagramObjects;
      for (var j=0;j<dos.Count;j++){
        var dob = dos.GetAt(j);
        var el  = Repository.GetElementByID(dob.ElementID);
        if (!el) continue;
        var guid = el.ElementGUID;
        var rec  = infoByGuid[guid];
        if (!rec) continue;

        var target = (!isNaN(rec.old_bcol) ? rec.old_bcol : -1);
        var newStyle = setOrClearBCol(dob.Style, target);
        if (newStyle != String(dob.Style||"")){
          dob.Style = newStyle;
          dob.Update();
          changed=true;
          touched++;
        }
      }
      if (changed) d.Update();
      diagrams++;
    }
    for (var k=0;k<p.Packages.Count;k++) arguments.callee(p.Packages.GetAt(k));
  })(pkg);

  Repository.RefreshOpenDiagrams(true);
  var cur = Repository.GetCurrentDiagram(); if (cur) Repository.ReloadDiagram(cur.DiagramID);

  out("Done. Diagrams scanned: "+diagrams+" | diagram objects updated: "+touched);
}
main();





// %----Applies tags to RAVENS objects based on exported CSV ---%
// Tag RAVENS elements from CSV new_bcol using your color→role map (EA JScript)
function out(s){ Repository.EnsureOutputVisible("Script"); Session.Output(String(s)); }

// --- find package by exact name
function findPackageByName(name){
  for (var m=0; m<Repository.Models.Count; m++){
    var p = (function dfs(pkg){
      if (pkg.Name == name) return pkg;
      for (var i=0; i<pkg.Packages.Count; i++){
        var hit = arguments.callee(pkg.Packages.GetAt(i));
        if (hit) return hit;
      }
      return null;
    })(Repository.Models.GetAt(m));
    if (p) return p;
  }
  return null;
}

// --- collect unique element GUIDs that appear on diagrams under a package
function collectElementGUIDsUnderPackage(pkg){
  var set = {};
  (function walk(p){
    for (var i=0; i<p.Diagrams.Count; i++){
      var d = p.Diagrams.GetAt(i);
      var dos = d.DiagramObjects;
      for (var j=0; j<dos.Count; j++){
        var el = Repository.GetElementByID(dos.GetAt(j).ElementID);
        if (el) set[el.ElementGUID] = true;
      }
    }
    for (var k=0; k<p.Packages.Count; k++) walk(p.Packages.GetAt(k));
  })(pkg);
  return set;
}

// --- read CSV -> guid -> new_bcol (int)
function readCsvNewBcol(csvPath){
  var fso = new ActiveXObject("Scripting.FileSystemObject");
  if (!fso.FileExists(csvPath)){ out("ERROR: CSV not found: " + csvPath); return {}; }
  var f = fso.OpenTextFile(csvPath, 1, false); // ForReading
  var map = {}, header = true;
  while(!f.AtEndOfStream){
    var line = f.ReadLine();
    if (header){ header=false; continue; }
    if (!line) continue;
    var p = line.split(","); // ea_guid,element_id,new_bcol,old_bcol
    if (p.length < 3) continue;
    var g = p[0];
    var nb = (p[2] === "" ? NaN : parseInt(p[2], 10));
    if (g && !isNaN(nb)) map[g] = nb;
  }
  f.Close();
  return map;
}

// --- your color → ravensRole mapping
function roleForBcol(bcol){
  // {13353215 : 'pink', 14524637: 'rootClass', 15453831: 'compoundClass',
  //  13499135 : 'yellowClass', 10025880 : 'embeddedClass', 16777215 : 'white'}
  if (bcol === 13353215) return "pink";
  if (bcol === 14524637) return "rootClass";
  if (bcol === 15453831) return "compoundClass";
  if (bcol === 13499135) return "yellowClass";
  if (bcol === 10025880) return "embeddedClass";
  if (bcol === 16777215) return "white";
  return null;
}

function main(){
  var CSV_IN = "X:\\\\Research\\\\Ravens\\\\network copy\\\\cim\\\\original\\\\ravens_elements_colors.csv"; // Step 1 output
  var TARGET_PACKAGE = "RAVENS";
  var TAG_NAME = "ravensRole";

  out("Tagging elements under package '" + TARGET_PACKAGE + "' from CSV new_bcol …");

  var pkg = findPackageByName(TARGET_PACKAGE);
  if (!pkg){ out("ERROR: package not found: " + TARGET_PACKAGE); return; }

  var guidSet = collectElementGUIDsUnderPackage(pkg);
  var newBcolByGuid = readCsvNewBcol(CSV_IN);

  var tagged=0, already=0, skipped=0, missing=0;

  for (var g in guidSet){
    if (!guidSet[g]) continue;
    var nb = newBcolByGuid.hasOwnProperty(g) ? newBcolByGuid[g] : NaN;
    if (isNaN(nb)){ skipped++; continue; }              // not in CSV (no explicit color in NEW)
    var role = roleForBcol(nb);
    if (!role){ skipped++; continue; }                  // color not mapped

    var el = Repository.GetElementByGUID(g);
    if (!el){ missing++; continue; }

    try{
      var tvc = el.TaggedValues;

      // upsert ravensRole
      var found = false;
      for (var i=0; i<tvc.Count; i++){
        var tv = tvc.GetAt(i);
        if (tv.Name == TAG_NAME){
          found = true;
          if (tv.Value != role){
            tv.Value = role;
            tv.Update();
            el.Update();
            tagged++;
          } else {
            already++;
          }
          break;
        }
      }
      if (!found){
        var nt = tvc.AddNew(TAG_NAME, role);
        nt.Update();
        tvc.Refresh();
        el.Update();
        tagged++;
      }
    }catch(e){
      skipped++; // uncomment to debug: out("WARN " + g + ": " + e.description);
    }
  }

  Repository.RefreshOpenDiagrams(true);
  var cur = Repository.GetCurrentDiagram(); if (cur) Repository.ReloadDiagram(cur.DiagramID);

  out("Done. Set/updated: " + tagged + " | already correct: " + already + " | skipped: " + skipped + " | missing: " + missing);
}
main();



