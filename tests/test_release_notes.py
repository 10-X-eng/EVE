import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'addin/STEVE'))
from steve.release_notes import ReleaseNotes, highlights
from steve.version import VERSION


class ReleaseNotesTests(unittest.TestCase):
    def test_acknowledgement_survives_restart_and_a_new_version_is_unread(self):
        with tempfile.TemporaryDirectory() as home:
            notes = ReleaseNotes(home)
            self.assertTrue(notes.unread())
            notes.acknowledge(VERSION)
            self.assertFalse(ReleaseNotes(home).unread())
            with patch('steve.release_notes.VERSION', '99.0.0'):
                self.assertTrue(notes.unread())
            with self.assertRaises(ValueError):
                notes.acknowledge('0.0.0')
            self.assertFalse(notes.unread())

    def test_corrupt_or_interrupted_acknowledgement_keeps_notes_available(self):
        with tempfile.TemporaryDirectory() as home:
            notes = ReleaseNotes(home)
            notes.path.write_text('{bad')
            self.assertTrue(notes.unread())
            with patch.object(Path, 'replace', side_effect=OSError('interrupted')):
                with self.assertRaises(OSError):
                    notes.acknowledge(VERSION)
            self.assertEqual(notes.path.read_text(), '{bad')
            notes.acknowledge(VERSION)
            self.assertFalse(notes.unread())
            self.assertEqual(json.loads(notes.path.read_text())['version'], VERSION)

    def test_notes_are_bundled_and_bounded(self):
        notes = highlights()
        self.assertEqual(notes['version'], VERSION)
        self.assertLess(len(json.dumps(notes)), 1800)
        self.assertTrue(notes['items'])
