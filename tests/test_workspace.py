"""Frontend route checks using isolated protocol fixtures, never live writes."""
import unittest
from unittest.mock import patch
from html.parser import HTMLParser
import test_dashboard_v2 as legacy


class Options(HTMLParser):
    def __init__(self):
        super().__init__(); self.select=None; self.disabled=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='select': self.select=attrs.get('id')
        if tag=='option' and self.select=='labVariable': self.disabled.append('disabled' in attrs)
    def handle_endtag(self,tag):
        if tag=='select': self.select=None


class WorkspaceTests(unittest.TestCase):
    def setUp(self): legacy.DashboardV2Tests.setUp(self)
    def tearDown(self): legacy.DashboardV2Tests.tearDown(self)

    def test_workspace_preserves_routes_and_local_assets(self):
        for path in ('/','/inicio','/inicio/anterior','/inicio/explorar','/v2','/v2/datos'):
            self.assertEqual(self.client.get(path).status_code,200)
        text=self.client.get('/inicio/explorar').get_data(as_text=True)
        self.assertIn('aria-describedby="labSummary"',text)
        self.assertIn('Fechas personalizadas UTC',text)
        self.assertIn('No se calculan correlaciones',text)
        self.assertNotIn('<script src="https://',text)
        for file in ('css/workspace.css','js/workspace.js'):
            with self.client.get('/static/v2/'+file) as response:self.assertEqual(response.status_code,200)

    def test_unconnected_variables_are_disabled_instead_of_synthetic(self):
        parser=Options();parser.feed(self.client.get('/inicio/explorar').get_data(as_text=True))
        self.assertEqual(parser.disabled,[False])

    def test_unavailable_database_does_not_expose_path(self):
        with patch('app.DB',self.db.parent/'missing.db'):
            response=self.client.get('/inicio/explorar')
        self.assertEqual(response.status_code,503)
        text=response.get_data(as_text=True)
        self.assertIn('No se pudo consultar la base local',text)
        self.assertNotIn(str(self.db.parent),text)
