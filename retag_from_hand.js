//!INC Local Scripts.EAConstants-JScript

    // Update ravensRole for selected elements only.
    // NOTE: This script *only* clears/sets IDs we pass in. It will not touch any others.

    var ALL_IDS = [
    13134, 13144, 13149, 13161, 13165, 13167, 13196, 13201, 13207, 13210, 13211, 13217, 13220, 13225, 13233, 13238, 13241, 13243, 13245, 13255, 13256, 13261, 13266, 13267, 13268,
    13269, 13271, 13274, 13275, 13299, 13314, 13315, 13317, 13321, 13327, 13329, 13344, 13348, 13350, 13351, 13358, 13359, 13360, 13362, 13363, 13386, 13387, 13388, 13389, 15109,
    15418, 20259, 20262, 21186, 21718, 21719, 21764, 21767, 21770, 21773, 21775, 21780, 27817, 27818, 27822, 28091, 28093, 28107, 31508, 31816, 31877, 31881, 37434, 37487, 37503,
    37549, 37564, 37611, 37615, 37643, 37651, 37667, 37690, 37764, 37767, 37807, 37819, 37855, 37915, 37949, 38068, 38081, 38121, 38167, 38201, 38237, 38329, 38470, 38618, 38625,
    38632, 38649, 38817, 38842, 38896, 38897, 38900, 38901, 38902, 38903, 38908, 38918, 38919, 38921, 38922, 38927, 38933, 38934, 38937, 38938, 38944, 38946, 38947, 38948, 38949,
    38950, 38951, 38952, 38957, 38958, 38961, 38962, 38963, 38987, 38989, 38991, 38992, 38995, 38996, 39048
];
    var INHERITONLY_IDS = [
    13144, 13161, 13165, 13196, 13201, 13207, 13210, 13211, 13217, 13220, 13233, 13238, 13241, 13243, 13245, 13255, 13256, 13261, 13268, 13269, 13271, 13274, 13275, 13299, 13314,
    13315, 13317, 13321, 13327, 13329, 13344, 13348, 13350, 13351, 13358, 13359, 13360, 13362, 13363, 13386, 13388, 15109, 15418, 20259, 20262, 21186, 21718, 21719, 21767, 21770,
    21775, 21780, 27817, 27818, 27822, 28093, 28107, 31508, 31816, 31877, 31881, 37434, 37487, 37503, 37549, 37564, 37611, 37615, 37643, 37651, 37690, 37767, 37807, 37819, 37855,
    37915, 37949, 38068, 38081, 38121, 38201, 38237, 38329, 38470, 38618, 38625, 38632, 38649, 38842, 38896, 38900, 38901, 38902, 38903, 38918, 38921, 38922, 38927, 38933, 38934,
    38937, 38938, 38944, 38946, 38947, 38948, 38949, 38950, 38951, 38952, 38958, 38961, 38962, 38963, 38987, 38989, 38995, 38996
];
    var CONTAINER_IDS = [
    13134, 13149, 13225, 13266, 13387, 21764, 21773, 28091, 37667, 37764, 38167, 38908, 38919, 38957, 38991, 38992
];
    var SUBSTITUTABLE_IDS = [
    13167, 13267, 13389, 38817, 38897, 39048
];

    // --- helpers ---
    function setMsg(label, arr) {
        Session.Output(label + " (" + arr.length + "): " + (arr.length ? arr.slice(0, 10).join(", ") + (arr.length>10?" ...":"") : "[]"));
    }

    function clearSelected(ids) {
        for (var i=0; i<ids.length; i++) {
            var el = Repository.GetElementByID(ids[i]);
            if (!el) continue;
            if (el.Name && el.Name === "Root") continue;

            var tv = null;
            try { tv = el.TaggedValues.GetByName("ravensRole"); } catch(e) { tv = null; }
            if (tv != null) {
                // Only clear if it's one of the not-concrete roles we're managing
                if (tv.Value === "containerClass" || tv.Value === "substitutableClass" || tv.Value === "inheritOnlyClass") {
                    tv.Value = "";
                    tv.Update();
                    el.TaggedValues.Refresh();
                }
            }
            el.Update();
        }
    }

    function setRoleByList(idList, roleValue) {
        for (var i=0; i<idList.length; i++) {
            var id = idList[i];
            var el = Repository.GetElementByID(id);
            if (!el) continue;
            if (el.Name && el.Name === "Root") continue;

            var tv = null;
            try { tv = el.TaggedValues.GetByName("ravensRole"); } catch(e) { tv = null; }
            if (tv == null) {
                tv = el.TaggedValues.AddNew("ravensRole", "");
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

        // Warn if overlaps (should be none if guess function enforces precedence)
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
    