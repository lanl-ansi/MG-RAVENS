//!INC Local Scripts.EAConstants-JScript

    // Single script to re-tag not-concrete classes in EA (skips literal 'Root').
    // Steps:
    //  1) Clear any existing ravensRole values in {containerClass, substitutableClass, inheritOnlyClass}
    //  2) Assign new ravensRole per the arrays below
    // Paste into EA's Script window (JScript). Run main().

    var CONTAINER_IDS = [
    38167
];
    var SUBSTITUTABLE_IDS = [
    13134, 13149, 13167, 13225, 13266, 13267, 21764, 28091, 37748, 37764, 38897, 38919
];
    var INHERITONLY_IDS = [
    13124, 13161, 13165, 13177, 13179, 13180, 13181, 13182, 13200, 13201, 13210, 13211, 13217, 13220, 13223, 13229, 13233, 13238, 13241, 13244, 13255, 13261, 13271, 13275, 13299,
    13314, 13315, 13317, 13355, 13358, 13360, 13363, 13389, 15414, 15418, 20259, 20261, 20262, 21186, 21718, 21719, 21721, 21722, 22332, 25116, 27817, 27818, 27822, 28093, 28107,
    36033, 37434, 37506, 37538, 37564, 37615, 37643, 37651, 37667, 37690, 37807, 37819, 37855, 37949, 38036, 38113, 38164, 38279, 38280, 38305, 38365, 38372, 38423, 38460, 38467,
    38470, 38475, 38618, 38632, 38654, 38671, 38817, 38840, 38842, 38896, 38900, 38901, 38902, 38903, 38911, 38912, 38922, 38923, 38932, 38937, 38938, 38944, 38968, 38985, 38987,
    38991, 38992, 38995, 38997, 38998, 39000, 39001, 39002, 39003, 39063
];

    // --- helpers ---

    function parseIdsFromSQL(xmlText) {
        var rx = /<Object_ID>(\d+)<\/Object_ID>/g, out=[], m=null;
        while ((m = rx.exec(xmlText)) != null) out.push(parseInt(m[1], 10));
        return out;
    }

    function clearExistingNotConcrete() {
        var sql = "select o.Object_ID as Object_ID\n" +
                "from t_object o\n" +
                "join t_objectproperties p on p.Object_ID = o.Object_ID\n" +
                "where p.Property = 'ravensRole'\n" +
                "  and p.Value in ('containerClass','substitutableClass','inheritOnlyClass')";
        var xml = Repository.SQLQuery(sql);
        var ids = parseIdsFromSQL(xml);
        for (var i=0; i<ids.length; i++) {
            var el = Repository.GetElementByID(ids[i]);
            if (!el) continue;
            var tv = null;
            try { tv = el.TaggedValues.GetByName("ravensRole"); } catch(e) { tv = null; }
            if (tv != null) { tv.Value = ""; tv.Update(); el.TaggedValues.Refresh(); }
            el.Update();
        }
    }

    function setRoleByList(idList, roleValue) {
        for (var i=0; i<idList.length; i++) {
            var id = idList[i];
            var el = Repository.GetElementByID(id);
            if (!el) continue;
            var tv = null;
            try { tv = el.TaggedValues.GetByName("ravensRole"); } catch(e) { tv = null; }
            if (tv == null) {
                tv = el.TaggedValues.AddNew("ravensRole", "");
            }
            tv.Value = roleValue;
            tv.Update();
            el.TaggedValues.Refresh();
            el.Update();
        }
    }

    function main() {
        Session.Output("Re-tagging not-concrete roles: starting...");
        clearExistingNotConcrete();

        setRoleByList(CONTAINER_IDS, "containerClass");
        setRoleByList(SUBSTITUTABLE_IDS, "substitutableClass");
        setRoleByList(INHERITONLY_IDS, "inheritOnlyClass");

        Session.Output("Re-tagging complete. Containers=" + CONTAINER_IDS.length
        + ", Substitutables=" + SUBSTITUTABLE_IDS.length
        + ", InheritOnly=" + INHERITONLY_IDS.length);
    }

    main();
    