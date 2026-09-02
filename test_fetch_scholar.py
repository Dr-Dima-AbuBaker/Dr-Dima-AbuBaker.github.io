"""Tests for fetch_scholar.py parsing and merge logic.

Fixtures are copied from SerpApi's own documented sample responses
(serpapi.com/google-scholar-author-api and .../google-scholar-author-citation)
so the parser is checked against the real field names without spending an
API call.

Run:  python test_fetch_scholar.py
"""

import unittest

import fetch_scholar as fs


AUTHOR_ARTICLE = {
    "title": "Model-based analysis of ChIP-Seq (MACS)",
    "link": "https://scholar.google.com/citations?view_op=view_citation&user=LSsXyncAAAAJ",
    "citation_id": "LSsXyncAAAAJ:2osOgNQ5qMEC",
    "authors": "Y Zhang, T Liu, CA Meyer, J Eeckhoute, DS Johnson, BE Bernstein, ...",
    "publication": "Genome biology 9 (9), 1-9, 2008",
    "cited_by": {
        "value": 9186,
        "link": "https://scholar.google.com/scholar?cites=14252090027271643524",
    },
    "year": "2008",
}

CITATION_DETAIL = {
    "title": "Genome-wide analysis of estrogen receptor binding sites",
    "link": "https://www.nature.com/articles/ng1901",
    "authors": "Jason S Carroll, Clifford A Meyer, Jun Song, Wei Li",
    "publication_date": "2006/11",
    "journal": "Nature genetics",
    "volume": "38",
    "description": "The estrogen receptor is the master transcriptional regulator.",
    "total_citations": {"cited_by": {"total": 1464}},
}


class TestParseCitations(unittest.TestCase):
    def test_reads_value_field(self):
        self.assertEqual(fs.parse_citations(AUTHOR_ARTICLE), 9186)

    def test_missing_cited_by_is_zero(self):
        # Scholar omits `cited_by` entirely for never-cited papers.
        self.assertEqual(fs.parse_citations({"title": "New paper"}), 0)

    def test_null_value_is_zero(self):
        self.assertEqual(fs.parse_citations({"cited_by": {"value": None}}), 0)


class TestParseYear(unittest.TestCase):
    def test_string_year(self):
        self.assertEqual(fs.parse_year("2008"), 2008)

    def test_missing_year(self):
        self.assertEqual(fs.parse_year(None), 0)
        self.assertEqual(fs.parse_year(""), 0)


class TestArticleToPublication(unittest.TestCase):
    def test_article_only(self):
        pub = fs.article_to_publication(AUTHOR_ARTICLE)
        self.assertEqual(pub["title"], "Model-based analysis of ChIP-Seq (MACS)")
        self.assertEqual(pub["year"], 2008)
        self.assertEqual(pub["citations"], 9186)
        self.assertEqual(pub["venue"], "Genome biology 9 (9), 1-9, 2008")
        self.assertIn("Model-based analysis", pub["bibtex"])

    def test_details_override_and_enrich(self):
        pub = fs.article_to_publication(AUTHOR_ARTICLE, CITATION_DETAIL)
        # Detail record wins for title, venue, abstract and publisher link.
        self.assertEqual(pub["venue"], "Nature genetics")
        self.assertEqual(pub["pub_url"], "https://www.nature.com/articles/ng1901")
        self.assertTrue(pub["description"].startswith("The estrogen receptor"))
        # Citation count still comes from the article, not the detail record.
        self.assertEqual(pub["citations"], 9186)

    def test_type_is_keyword_matched_on_venue(self):
        # guess_type is a keyword check, so a journal whose name lacks the word
        # "journal" (e.g. "Nature genetics") is labelled a conference. Only
        # affects newly-added papers; every venue on this profile matches.
        journal = fs.article_to_publication(
            AUTHOR_ARTICLE, dict(CITATION_DETAIL, journal="Journal of Prosthodontics"))
        self.assertEqual(journal["type"], "journal")
        unmatched = fs.article_to_publication(AUTHOR_ARTICLE, CITATION_DETAIL)
        self.assertEqual(unmatched["type"], "conference")

    def test_year_falls_back_to_publication_date(self):
        article = dict(AUTHOR_ARTICLE, year="")
        pub = fs.article_to_publication(article, CITATION_DETAIL)
        self.assertEqual(pub["year"], 2006)

    def test_long_abstract_is_truncated(self):
        details = dict(CITATION_DETAIL, description="x" * 500)
        pub = fs.article_to_publication(AUTHOR_ARTICLE, details)
        self.assertEqual(len(pub["description"]), 203)
        self.assertTrue(pub["description"].endswith("..."))


class TestMerge(unittest.TestCase):
    def existing(self, **overrides):
        pub = {
            "title": "Stress experienced by dental students",
            "citations": 34,
            "url": "https://example.com/paper",
            "pdfUrl": "https://example.com/paper",
        }
        pub.update(overrides)
        return [pub]

    def fetched(self, **overrides):
        pub = {
            "title": "Stress experienced by dental students",
            "authors": "D Abu Baker",
            "year": 2024,
            "venue": "Journal of Occupational Health",
            "citations": 40,
            "description": "",
            "type": "journal",
            "pub_url": "https://example.com/new",
            "bibtex": "@article{}",
        }
        pub.update(overrides)
        return [pub]

    def test_updates_citation_count(self):
        existing = self.existing()
        fs.merge_publications(existing, self.fetched(), "D Abu Baker")
        self.assertEqual(existing[0]["citations"], 40)

    def test_matches_on_normalized_title(self):
        existing = self.existing(title="Stress Experienced By Dental Students.")
        result = fs.merge_publications(existing, self.fetched(), "D Abu Baker")
        self.assertEqual(len(result), 1, "case/period differences must not create a duplicate")
        self.assertEqual(result[0]["citations"], 40)

    def test_zero_count_does_not_wipe_existing_citations(self):
        # Guards against a parse regression silently zeroing the site's numbers.
        existing = self.existing()
        fs.merge_publications(existing, self.fetched(citations=0), "D Abu Baker")
        self.assertEqual(existing[0]["citations"], 34)

    def test_does_not_overwrite_curated_fields(self):
        existing = self.existing(image="images/publications/custom.svg",
                                 description="Hand-written summary")
        fs.merge_publications(existing, self.fetched(description="Scholar abstract"),
                              "D Abu Baker")
        self.assertEqual(existing[0]["image"], "images/publications/custom.svg")
        self.assertEqual(existing[0]["description"], "Hand-written summary")
        self.assertEqual(existing[0]["url"], "https://example.com/paper")

    def test_fills_placeholder_urls(self):
        existing = self.existing(url="#", pdfUrl="#")
        fs.merge_publications(existing, self.fetched(), "D Abu Baker")
        self.assertEqual(existing[0]["url"], "https://example.com/new")
        self.assertEqual(existing[0]["pdfUrl"], "https://example.com/new")

    def test_adds_new_paper_with_placeholders(self):
        existing = self.existing()
        result = fs.merge_publications(existing, self.fetched(title="A brand new paper"),
                                       "D Abu Baker")
        self.assertEqual(len(result), 2)
        added = result[1]
        self.assertEqual(added["image"], fs.PLACEHOLDER_IMAGE)
        self.assertEqual(added["thumbnail"], fs.PLACEHOLDER_THUMB)
        self.assertEqual(added["highlightAuthor"], "D Abu Baker")

    def test_paper_missing_from_scholar_is_kept(self):
        # OpenAlex/Scholar coverage gaps must never delete a curated entry.
        existing = self.existing()
        result = fs.merge_publications(existing, self.fetched(title="Different paper"),
                                       "D Abu Baker")
        titles = [p["title"] for p in result]
        self.assertIn("Stress experienced by dental students", titles)


class TestBibtex(unittest.TestCase):
    def test_journal_entry(self):
        entry = fs.format_bibtex({"authors": "Dima Abu Baker and X", "title": "T",
                                  "year": 2026, "venue": "Digital Dentistry Journal"})
        self.assertTrue(entry.startswith("@article{dima2026,"))

    def test_conference_entry(self):
        entry = fs.format_bibtex({"authors": "Dima Abu Baker", "title": "T",
                                  "year": 2026, "venue": "IADR Annual Meeting"})
        self.assertTrue(entry.startswith("@inproceedings{"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
