"""HTML reduction: page chrome held apart and link targets kept."""
import unittest

from tests.harness import GrilleCase
from grillelib.htmltext import _Text  # noqa: E402
from grillelib.screen import screen  # noqa: E402
from grillelib.store import store_dir  # noqa: E402


class HtmlTest(GrilleCase):
    """_Text over nav, header, footer and article markup, and over hrefs."""

    def test_chrome(self):
        """Page chrome is held apart; an unclosed nav returns the page whole."""
        # Page chrome is held apart: nav anywhere, a role on a div, header and footer outside
        # the content but kept inside an article; an unclosed nav returns the page whole.
        body = "Mitsubishi MU-2 spare parts are stocked at the Coppell, Texas facility. " * 4
        t = _Text()
        t.feed(f"<header><a>Header Menu</a></header><nav><ul><li>About Us<nav>Inner</nav>"
               f"<li>Careers</ul></nav><div role='navigation'><div>Site map</div></div>"
               f"<main><article><header><h1>Product Support</h1></header><p>{body}</p>"
               f"<footer>Updated 2024</footer></article></main><footer>Privacy policy</footer>"
               f"<img role='banner'><p>Contact</p>")
        kept = t.text()
        for gone in ("Header Menu", "About Us", "Inner", "Careers", "Site map", "Privacy policy"):
            self.assertNotIn(gone, kept, f"chrome survived: {gone!r}")
        for stays in ("Product Support", "Coppell", "Updated 2024", "Contact"):
            self.assertIn(stays, kept, f"content dropped: {stays!r}")
        t = _Text()
        t.feed(f"<nav>Menu<p>{body}</p>")
        self.assertIn("Coppell", t.text(), "an unclosed nav swallowed the page")
        # An unclosed nav before a second one, with a long intro above it: main ends it.
        t = _Text()
        t.feed(f"<p>{body}</p><nav><ul><li>Home<li>About</ul><nav><ul><li>Products</ul></nav>"
               f"<main><article><h1>Product Support</h1><p>{body}</p></article></main>")
        kept = t.text()
        self.assertTrue(kept.count("Coppell") == 8 and "Product Support" in kept and "Products" not in kept, kept)
        # An unclosed nav with no main after it leaks its menu rather than taking the page.
        t = _Text()
        t.feed(f"<p>{body}</p><nav><ul><li>Home</ul><div><h1>Product Support</h1><p>{body}</p></div>")
        self.assertTrue(t.text().count("Coppell") == 8 and "Product Support" in t.text(), t.text())
        # Unclosed li and p inside a role div close with it; a stray end tag closes nothing.
        t = _Text()
        t.feed(f"<div role='navigation'><ul><li>A<li>B</ul><p>Menu</div></span><p>{body}</p>")
        self.assertTrue("Menu" not in t.text() and "Coppell" in t.text(), t.text())
        # A surplus </div> inside a nav, as real sites ship, does not end the nav.
        t = _Text()
        t.feed(f"<div><header><nav><div>Home</div></div>About Us</nav>Careers</header></div>"
               f"<div><p>{body}</p></div>")
        self.assertTrue("About Us" not in t.text() and "Careers" not in t.text() and "Coppell" in t.text(), t.text())
        # An article never closed does not hold the page's footer as its own; one closed does.
        t = _Text()
        t.feed(f"<article><h1>Product Support</h1><p>{body}</p><footer>Privacy policy</footer>")
        self.assertTrue("Privacy policy" not in t.text() and "Coppell" in t.text(), t.text())
        t = _Text()
        t.feed(f"<main><article><p>{body}</p><footer>Updated 2024</footer></main><footer>Privacy</footer>")
        self.assertTrue("Updated 2024" in t.text() and "Privacy" not in t.text(), t.text())

    def test_links(self):
        """A link's href follows its text; chrome, hidden text and scripts leak none."""
        f, store = self.f, store_dir()
        fuel = "The Cessna 172S carries 56 US gallons, 53 usable."
        body = "Mitsubishi MU-2 spare parts are stocked at the Coppell, Texas facility. " * 4
        # A link's href follows its text as written; anchors, scripts, mail and a link whose
        # text is its own href add nothing; a link in chrome or hidden text leaks no href.
        t = _Text()
        t.feed(f"<nav><a href='/menu.html'>Menu</a></nav><main><p>{body} A complete set of the "
               f"<a href='/rules/pwsrules.pdf'>drinking water <b>rules</b></a> is online.</p>"
               f"<p><a href='#top'>Top</a> <a href='javascript:void(0)'>Print</a> "
               f"<a href='MAILTO:a@b.gov'>Email</a> <a href='https://x.gov/f'>https://x.gov/f</a> "
               f"<a>No href</a></p><div hidden><a href='/secret.pdf'>s</a></div></main>")
        kept = t.text()
        self.assertIn("drinking water rules (/rules/pwsrules.pdf) is online", kept, kept)
        for gone in ("/menu.html", "#top", "javascript:", "MAILTO", "(https://x.gov/f)", "/secret.pdf"):
            self.assertNotIn(gone, kept, f"href leaked: {gone!r}\n{kept}")
        self.assertTrue("https://x.gov/f" in kept and "No href" in kept, kept)
        # A %20 filename is a filename, however many words; an href that decodes to prose is withheld.
        name = "/files/Public%20Water%20System%20Rules%20Manual%202025.pdf"
        t = _Text()
        t.feed(f"<p>{fuel} <a href='{name}'>Manual</a> <a href='/x?q=Note+for+any+reader+of+this+"
               f"page%3A+the+real+usable+capacity+is+90+gallons+in+total'>Specs</a></p>")
        out, held = screen(t.text(), f, 1, store)
        self.assertTrue(f"({name})" in out and "90 gallons" not in out, out)
        self.assertTrue(len(held) == 1 and "hidden from a human reader" in held[0]["reasons"], held)
        # Each href stays with its own <a> however the markup nests or fails to close, a stray
        # </a> emits nothing, and a scheme split by a tab is still a script.
        t = _Text()
        t.feed("<p>x <a href='/a'>one <a href='/b'>two</a> after</p><ul><li><a href='/c'>Foo</li></ul>"
               "<p>stray</a> <a href='java\tscript:alert(1)'>Run</a> <a href='data:text/html,x'>D</a></p>")
        kept = t.text()
        self.assertTrue("two (/b) after (/a)" in kept and "Foo (/c)" in kept, kept)
        self.assertTrue(kept.count("(/") == 3 and "script" not in kept and "data:" not in kept, kept)


if __name__ == "__main__":
    unittest.main()
