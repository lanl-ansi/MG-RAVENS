//!INC Local Scripts.EAConstants-JScript

// Update ravensRole for selected elements only.
// NOTE: This script *only* clears/sets IDs we pass in. It will not touch any others.

var ALL_IDS = [
    13134, 13149, 13167, 13225, 13266, 13267, 13276, 13387, 21764, 21773, 28091, 37667, 37764, 38167, 38897, 38908, 38919, 38957, 38991, 38992
];
var INHERITONLY_IDS = [];
var CONTAINER_IDS = [
    13134, 13149, 13167, 13225, 13266, 13267, 13276, 13387, 21764, 21773, 28091, 37667, 37764, 38167, 38897, 38908, 38919, 38957, 38991, 38992
];
var SUBSTITUTABLE_IDS = [];

// --- helpers ---
function setMsg(label, arr) {
    Session.Output(label + " (" + arr.length + "): " + (arr && arr.length ? arr.slice(0, 10).join(", ") + (arr.length>10?" ...":"") : "[]"));
}

function clearSelected(ids) {
    for (var i=0; i<ids.length; i++) {
        var el = Repository.GetElementByID(ids[i]);
        if (!el) continue;
        if (el.Name && el.Name === "Root") continue;

        var tv = null;
        for (var t=0; t<el.TaggedValues.Count; t++) {
            var candidate = el.TaggedValues.GetAt(t);
            if (candidate && candidate.Name === "ravensRole") {
                tv = candidate; break;
            }
        }
        if (!tv) {
            // create missing tag
            tv = el.TaggedValues.AddNew("ravensRole", "");
            tv.Value = "";
            tv.Update();
            el.TaggedValues.Refresh();
        }

        // don't clear concrete roles
        if (tv.Value === "rootClass" || tv.Value === "embeddedClass") continue;

        // clear only if it's a not-concrete role we are resetting
        if (tv.Value === "inheritOnlyClass" || tv.Value === "containerClass" || tv.Value === "substitutableClass") {
            tv.Value = "";
            tv.Update();
            el.TaggedValues.Refresh();
            el.Update();
        }
    }
}

function setRoleByList(ids, roleValue) {
    for (var i=0; i<ids.length; i++) {
        var el = Repository.GetElementByID(ids[i]);
        if (!el) continue;
        if (el.Name && el.Name === "Root") continue;

        var tv = null;
        for (var t=0; t<el.TaggedValues.Count; t++) {
            var candidate = el.TaggedValues.GetAt(t);
            if (candidate && candidate.Name === "ravensRole") {
                tv = candidate; break;
            }
        }
        if (!tv) {
            tv = el.TaggedValues.AddNew("ravensRole", "");
            tv.Value = "";
            tv.Update();
            el.TaggedValues.Refresh();
        }

        // don't overwrite concrete roles
        if (tv.Value === "rootClass" || tv.Value === "embeddedClass") continue;

        // skip if already the desired value to minimize churn
        if (tv.Value === roleValue) continue;

        tv.Value = roleValue;
        tv.Update();
        el.TaggedValues.Refresh();
        el.Update();
    }
}

function main() {
    Session.Output("Re-tagging selected not-concrete roles: starting...");
    setMsg("inheritOnly IDs", INHERITONLY_IDS);
    setMsg("container IDs", CONTAINER_IDS);
    setMsg("substitutable IDs", SUBSTITUTABLE_IDS);

    // Clear only those we will (re)set:
    clearSelected(ALL_IDS);

    // Because sets are expected disjoint, order is irrelevant; keep it stable.
    setRoleByList(INHERITONLY_IDS, "inheritOnlyClass");
    setRoleByList(CONTAINER_IDS,   "containerClass");
    setRoleByList(SUBSTITUTABLE_IDS, "substitutableClass");

    // Warn if overlaps (should be none if upstream enforces precedence)
    var warn = [];
    if (false) warn.push("inheritOnly ∩ container overlap exists");
    if (false) warn.push("inheritOnly ∩ substitutable overlap exists");
    if (false) warn.push("container ∩ substitutable overlap exists");
    if (warn.length) {
        for (var i=0; i<warn.length; i++) Session.Output("WARNING: " + warn[i]);
    }

    Session.Output("Done. Updated " + ALL_IDS.length + " element(s).");
}

main();
