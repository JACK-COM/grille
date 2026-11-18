"""PDF page labels and printed footer numbers."""
import unittest
import zlib

from tests.harness import GrilleCase, tiny_pdf
from grille import (_label, _pdf_tokens, footer_labels, page_labels)


def _labelled_pdf(packed):
    """Three pages labelled i, ii, 1: the /PageLabels tree in a plain catalog, or packed
    with the catalog in a Flate object stream as Acrobat writes it."""
    labels = b"<< /Nums [0 << /S /r >> 2 << /S /D /St 1 >>] >>"
    kids = b"[3 0 R 4 0 R 5 0 R]"
    page = b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 100] >>"
    catalog = b"<< /Type /Catalog /Pages 2 0 R /PageLabels 7 0 R >>"
    objs = {2: b"<< /Type /Pages /Kids " + kids + b" /Count 3 >>", 3: page, 4: page, 5: page}
    if packed:
        body = b"1 0 7 %d " % (len(catalog) + 1)
        data = catalog + b" " + labels
        raw = zlib.compress(body + data)
        objs[6] = (b"<< /Type /ObjStm /N 2 /First %d /Filter /FlateDecode /Length %d >>\nstream\n"
                   % (len(body), len(raw)) + raw + b"\nendstream")
    else:
        objs[1], objs[7] = catalog, labels
    return _raw_pdf(objs)


def _raw_pdf(objs, tail=b""):
    """Objects in the order given, then a trailer naming object 1 as the root: enough for
    page_labels, which never reads the xref."""
    out = bytearray(b"%PDF-1.5\n")
    for n, body in (objs.items() if isinstance(objs, dict) else objs):
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    return bytes(out + b"trailer\n<< /Root 1 0 R" + tail + b" >>\n%%EOF\n")


class LabelsTest(GrilleCase):
    """page_labels over number-tree shapes and hostile labels; footer_labels over printed numbers."""

    def test_page_labels(self):
        """The number-tree shapes and hostile labels the parser must survive."""
        d = self.d
        f = d / "labelled.pdf"
        cat = b"<< /Type /Catalog /PageLabels 7 0 R >>"

        def labels(objs, count, tail=b""):
            f.write_bytes(_raw_pdf(objs, tail))
            return page_labels(f, count)

        for packed in (False, True):
            f.write_bytes(_labelled_pdf(packed))
            self.assertEqual(page_labels(f, 3), {1: "i", 2: "ii", 3: "1"}, f"packed={packed}: {page_labels(f, 3)}")
        # 10 middle nodes of 30 one-page leaves: a guard keyed on parsed dicts lost most of them
        objs = {1: cat, 7: b"<< /Kids [" + b" ".join(b"%d 0 R" % (100 + m) for m in range(10)) + b"] >>"}
        for m in range(10):
            objs[100 + m] = b"<< /Kids [" + b" ".join(b"%d 0 R" % (1000 + 30 * m + j) for j in range(30)) + b"] >>"
            for j in range(30):
                k = 30 * m + j
                objs[1000 + k] = b"<< /Nums [%d << /S /D /St %d >>] >>" % (k, k + 101)
        got = labels(objs, 300)
        self.assertTrue(len(got) == 300 and got[1] == "101" and got[300] == "400", f"deep tree: {len(got)} labels")
        self.assertEqual(labels({1: cat, 7: b"<< /Kids [7 0 R 8 0 R] >>", 8: b"<< /Nums [0 << /S /r >>] >>"}, 2), {1: "i", 2: "ii"}, "a cyclic /Kids")
        self.assertEqual(labels({1: cat, 7: b"<< /Nums [0 << /S /r /St 3000000000 >>] >>"}, 2), {}, "a huge /St")
        self.assertEqual(labels({1: cat, 7: b"<< /Nums [0 << /S /D /P (\\101-) >>] >>"}, 2), {1: "A-1", 2: "A-2"}, "octal /P")
        self.assertEqual(labels({1: cat, 7: b"<< /Nums [0 << >>] >>"}, 2), {}, "an empty label prints nothing")
        self.assertEqual(labels({1: cat, 7: b"<< /Nums [0 << /S /D /P <0A0A23232070616765203939> >>] >>"}, 2), {}, "a label carrying a newline must never reach a heading")
        self.assertEqual(labels({1: cat, 7: b"<< /Nums [0 << /S /r >>] >>"}, 2, b" /Encrypt 9 0 R"), {}, "an encrypted file")
        newer = zlib.compress(b"7 0 << /Nums [0 << /S /D /St 50 >>] >>")
        self.assertEqual(labels([(1, cat), (7, b"<< /Nums [0 << /S /r >>] >>"),
                                 (9, b"<< /Type /ObjStm /N 1 /First 4 /Filter /FlateDecode >>\nstream\n"
                                  + newer + b"\nendstream")], 1),
                         {1: "50"}, "an update packed after the plain object it replaces")
        self.assertEqual(list(_pdf_tokens(b"(a(b)c) (x\\\ny) /Page#4cabels")), [("str", b"a(b)c"), ("str", b"xy"), ("name", "/PageLabels")])
        f.write_bytes(tiny_pdf("no labels"))
        self.assertEqual(page_labels(f, 1), {}, "a PDF with no labels")
        f.write_bytes(b"%PDF-1.4\n1 0 obj << /Type /Catalog /PageLabels 9 0 R")
        self.assertEqual(page_labels(f, 1), {}, "a broken PDF must yield no labels, never fail")
        self.assertEqual([_label("/R", 1994), _label("/a", 28), _label(None, 3), _label("/r", 4000)], ["MCMXCIV", "bb", "", None])

    def test_footer_labels(self):
        """Printed `Page N of M` footers label pages only as a consistent pattern."""
        body = ["Contents", "Preface"] + [f"Rule {k}\nsampling text\n\nOAR 333-061 Page {k} of 4" for k in range(1, 5)]
        self.assertEqual(footer_labels(body), {3: "1", 4: "2", 5: "3", 6: "4"}, footer_labels(body))
        self.assertEqual(footer_labels(body[:3] + ["Rule 2\nno footer"] + body[4:]), {3: "1", 5: "3", 6: "4"}, "a page with no footer stays unlabelled")
        many = ["cover", "contents"] + [f"text\nPage {k} of 20" for k in range(1, 21)]
        stray = footer_labels(many[:11] + ["text\nPage 10 of 21"] + many[12:])
        self.assertTrue(len(stray) == 19 and 12 not in stray and stray[13] == "11", f"a stray M: {stray}")
        self.assertEqual(footer_labels(body[:3] + [body[4], body[3]] + body[5:]), {}, "numbers that fall back")
        self.assertEqual(footer_labels(body[:5] + ["Rule 4\nsee Page 9 of 12 of the guide\n\nOAR 333-061 Page 4 of 4"]), {3: "1", 4: "2", 5: "3"}, "a page with two footers on its edges stays unlabelled")
        self.assertEqual(footer_labels(["Page 1 of 3\nx", "Page 2 of 3\ny", "Page 3 of 3\nz"]), {}, "matching numbers say nothing")
        self.assertEqual(footer_labels(["a", "b", "c", "x\nPage 1 of 9"]), {}, "one footer in four is not a pattern")
        self.assertEqual(footer_labels(body[:3] + ["Rule 2\nPage 3 of 4"] + body[4:]), {}, "N jumping ahead of the pages")
        self.assertEqual(footer_labels(body[:2] + ["Rule 1\nPage 0 of 4"] + body[3:]), {4: "2", 5: "3", 6: "4"}, "an N outside 1..M is no footer")


if __name__ == "__main__":
    unittest.main()
