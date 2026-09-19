import json
import unittest
from unittest import mock

from jev_linkmap import judge
from jev_linkmap.candidates import Index, build_queue
from jev_linkmap.crawl import parse_page, plain_copy
from jev_linkmap.run import agreement, link_map
from jev_linkmap.system2 import apply

HTML = """<html lang="en"><head><title>Lead routing playbook | Acme</title><meta name="description" content="How to route leads."></head>
<body><nav><a href="/contact">Contact us about anything at all today</a></nav><main><h1>Lead routing playbook</h1>
<p>Good lead routing starts with clean data, and <a href="/dedupe">duplicate management in Salesforce</a> comes first for every team.</p>
<p>When territory design changes, the lead routing rules in HubSpot must change with it, or reps lose deals.</p>
<script>var x = "lead routing rules in script";</script></main><footer><p>Footer words about lead routing that are long enough to be a block.</p></footer></body></html>"""


def page(url, title, body):
    return parse_page(url, f"<html lang='en'><head><title>{title}</title></head><body><main><h1>{title}</h1><p>{body}</p></main></body></html>")


RUBRIC = {"version": 1, "link_instructions": "L", "anchor_instructions": "A", "link_threshold": 0.7, "anchor_confidence": 0.5, "max_links_per_page": 2, "examples": []}


class Crawl(unittest.TestCase):
    def test_copy_excludes_chrome_and_scripts_and_marks_links(self):
        p = parse_page("https://www.acme.com/routing/", HTML)
        text = " ".join(p["blocks"])
        self.assertNotIn("Footer words", text)
        self.assertNotIn("in script", text)
        self.assertIn("⟦duplicate management in Salesforce⟧", text)
        self.assertEqual(p["links_out"], ["acme.com/dedupe"])
        self.assertIn("acme.com/contact", p["links_out_all"])
        self.assertEqual(p["key"], "acme.com/routing")
        self.assertNotIn("⟦", plain_copy(text))


class Candidates(unittest.TestCase):
    def setUp(self):
        self.pages = [
            parse_page("https://acme.com/routing/", HTML),
            page("https://acme.com/territory/", "Territory design for lead routing", "Territory design decides who owns which account. " * 12),
            page("https://acme.com/dedupe/", "Duplicate management in Salesforce", "Duplicate management keeps Salesforce clean for every team. " * 12),
            page("https://acme.com/pasta/", "Cooking pasta at home", "Boil water, add salt, cook the pasta until it is ready to eat. " * 12),
        ]

    def test_anchor_is_in_copy_and_never_inside_an_existing_link(self):
        idx = Index(self.pages)
        copy = plain_copy(" ".join(self.pages[0]["blocks"]))
        for j in (1, 2):
            for a in idx.anchors(0, j):
                self.assertIn(a["phrase"], copy)
                self.assertNotIn("duplicate management", a["phrase"].lower())
        self.assertTrue(any("territory design" in a["phrase"].lower() for a in idx.anchors(0, 1)))

    def test_queue_skips_pages_already_linked(self):
        job = build_queue(self.pages, k=3, min_words=10)[0]
        keys = [t["key"] for t in job["targets"]]
        self.assertNotIn("acme.com/dedupe", keys)
        self.assertEqual(keys[0], "acme.com/territory")


class Judge(unittest.TestCase):
    def setUp(self):
        a = lambda p: {"phrase": p, "sentence": f"We cover {p} here.", "block": 1, "score": 1}
        self.job = {"source": "s", "url": "https://acme.com/s", "targets": [
            {"id": "t1", "key": "a", "url": "https://acme.com/a", "title": "A", "about": "", "anchors": [a("lead routing"), a("territory design")]},
            {"id": "t2", "key": "b", "url": "https://acme.com/b", "title": "B", "about": "", "anchors": [a("lead routing rules")]},
            {"id": "t3", "key": "c", "url": "https://acme.com/c", "title": "C", "about": "", "anchors": []},
        ]}
        self.page = {"url": "https://acme.com/s", "title": "S", "blocks": ["We cover lead routing here."]}

    def test_jev_request_shape_and_verdicts(self):
        answers = {"t1_link": {"noul": 0.91}, "t1_anchor": {"choice": "a2", "confidence": 0.8}, "t2_link": {"noul": 0.2}, "t2_anchor": {"choice": "none", "confidence": 0.9}, "t3_link": {"noul": 0.95}}
        with mock.patch("jev_linkmap.jev.ask", return_value=(answers, {"seconds": 0.4, "cost": 0.0003, "input_tokens": 7000})) as ask:
            res = judge.judge_jev(self.job, self.page, RUBRIC)
        state, questions = ask.call_args[0]
        self.assertEqual(set(questions), {"t1_link", "t1_anchor", "t2_link", "t2_anchor", "t3_link"})
        self.assertIn("none", questions["t1_anchor"]["criteria"])
        self.assertEqual(res["verdicts"]["t1"], {"link": 0.91, "anchor": "a2", "anchor_confidence": 0.8})
        placed = judge.place_links(self.job, res["verdicts"], RUBRIC)
        self.assertEqual([(l["target"], l["anchor"]) for l in placed], [("https://acme.com/a", "territory design")])

    def test_no_anchor_means_no_link_however_sure(self):
        v = {"t3": {"link": 0.99, "anchor": "none", "anchor_confidence": 0.0}}
        self.assertEqual(judge.place_links(self.job, v, RUBRIC), [])

    def test_one_phrase_carries_one_link(self):
        v = {"t1": {"link": 0.9, "anchor": "a1", "anchor_confidence": 0.9}, "t2": {"link": 0.8, "anchor": "a1", "anchor_confidence": 0.9}}
        placed = judge.place_links(self.job, v, RUBRIC)
        self.assertEqual(len(placed), 1)
        self.assertEqual(placed[0]["target"], "https://acme.com/a")

    def test_frontier_answer_is_held_to_the_same_options(self):
        text = 'Here: {"t1": {"link": true, "anchor": "a1"}, "t2": {"link": true, "anchor": "a9"}, "t3": {"link": false, "anchor": "none"}}'
        with mock.patch("jev_linkmap.deep.call", return_value=(text, {"seconds": 7.0, "cost": 0.09})) as call:
            res = judge.judge_frontier(self.job, self.page, RUBRIC)
        self.assertEqual(call.call_args[0][0], "referee")
        self.assertEqual(res["verdicts"]["t1"]["link"], 1.0)
        self.assertEqual(res["verdicts"]["t2"]["anchor"], "none")  # an option that was never offered is not an anchor
        self.assertEqual(res["meter"]["cost"], 0.09)

    def test_agreement_and_refusals(self):
        jv = [{"source": "s", "verdicts": {"t1": {"link": 0.9, "anchor": "a1", "anchor_confidence": 0.9}, "t2": {"link": 0.9, "anchor": "a1", "anchor_confidence": 0.9}, "t3": {"link": 0.1, "anchor": "none", "anchor_confidence": 0}}, "meter": {}}]
        fr = [{"source": "s", "verdicts": {"t1": {"link": 1.0, "anchor": "a2", "anchor_confidence": 1}, "t2": {"link": 0.0, "anchor": "none", "anchor_confidence": 1}, "t3": {"link": 0.0, "anchor": "none", "anchor_confidence": 1}}, "meter": {}}]
        agr = agreement([self.job], jv, fr, RUBRIC)
        self.assertEqual((agr["decisions"], agr["jev_yes"], agr["frontier_yes"], agr["both_yes"]), (3, 2, 1, 1))
        self.assertAlmostEqual(agr["agree"], 0.6667, places=3)
        self.assertEqual(agr["same_anchor_when_both_yes"], 0.0)
        links, refused = link_map([self.job], [{"source": "s", "verdicts": {}, "meter": {}}], RUBRIC)
        self.assertEqual((links, refused), ([], ["https://acme.com/s"]))


class System2(unittest.TestCase):
    def test_rewrite_is_clamped_and_cannot_touch_the_link_cap(self):
        new = apply(RUBRIC, {"rubric": {"link_instructions": " new L ", "anchor_instructions": "new A", "link_threshold": 0.1, "anchor_confidence": 2, "max_links_per_page": 50, "examples": [str(i) for i in range(9)]}})
        self.assertEqual((new["version"], new["link_instructions"], new["link_threshold"], new["anchor_confidence"], new["max_links_per_page"], len(new["examples"])), (2, "new L", 0.5, 0.9, 2, 6))


class Deep(unittest.TestCase):
    def test_codex_backend_runs_read_only_and_reads_the_last_message(self):
        from jev_linkmap import deep

        class Proc:
            returncode = 0

            def __init__(self, cmd, **kw):
                self.cmd, self.cwd = cmd, kw["cwd"]

            def communicate(self, stdin, timeout=None):
                self.stdin = stdin
                open(self.cmd[self.cmd.index("-o") + 1], "w").write('{"ok": true}')
                return "", ""

        made = []
        with mock.patch.object(deep, "BACKEND", "codex"), mock.patch.object(deep, "CODEX_MODEL", ""), mock.patch("subprocess.Popen", side_effect=lambda cmd, **kw: made.append(Proc(cmd, **kw)) or made[-1]):
            text, meter = deep.call("system2", "SYSTEM BRIEF", "the rows")
        cmd = made[0].cmd
        self.assertEqual(cmd[:2], ["codex", "exec"])
        self.assertEqual(cmd[cmd.index("-s") + 1], "read-only")
        self.assertIn("--ephemeral", cmd)
        self.assertTrue(made[0].stdin.startswith("SYSTEM BRIEF") and made[0].stdin.endswith("the rows"))
        self.assertEqual((text, meter["cost"], meter["model"]), ('{"ok": true}', 0.0, "codex:default"))

    def test_editor_pass_cuts_whatever_it_did_not_approve(self):
        from jev_linkmap import verify

        link = lambda n: {"source": f"https://a.com/p{n}/", "sentence": "s", "anchor": "a", "target_title": "T"}
        with mock.patch("jev_linkmap.deep.call", return_value=('{"1": true, "2": false}', {"seconds": 1, "cost": 0.01})):
            keep, _ = verify.review([(1, link(1)), (2, link(2)), (3, link(3))])
        self.assertEqual(keep, {1: True, 2: False, 3: False})


if __name__ == "__main__":
    unittest.main()
