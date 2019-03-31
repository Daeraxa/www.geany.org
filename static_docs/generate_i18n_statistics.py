# -*- coding: utf-8 -*-
# LICENCE: This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from json import dump, JSONEncoder
from os import listdir
from os.path import join, splitext
from subprocess import CalledProcessError, check_output, STDOUT
from time import time
import re

from babel import Locale


STATISTICS_REGEXP = re.compile(
    r'(?P<translated>\d+) translated messages(, (?P<fuzzy>\d+) fuzzy translations)?(, (?P<untranslated>\d+) untranslated messages)?')  # noqa: E501 pylint: disable=line-too-long
LAST_TRANSLATOR_REGEXP = re.compile(r'^"Last-Translator: (?P<name>[\w -]+)\s*<?.+')


class TranslationStatistics(object):

    # ----------------------------------------------------------------------
    def __init__(
            self,
            translated,
            fuzzy,
            untranslated,
            percentage_translated=None,
            percentage_fuzzy=None,
            percentage_untranslated=None):
        self.translated = translated
        self.fuzzy = fuzzy
        self.untranslated = untranslated
        self.percentage_translated = percentage_translated
        self.percentage_fuzzy = percentage_fuzzy
        self.percentage_untranslated = percentage_untranslated


class MessageCatalog(object):

    # ----------------------------------------------------------------------
    def __init__(self, filename, language_name, language_code, last_translator, statistics=None):
        self.filename = filename
        self.language_name = language_name
        self.language_code = language_code
        self.last_translator = last_translator
        self.statistics = statistics


class SimpleObjectToJSONEncoder(JSONEncoder):

    # ----------------------------------------------------------------------
    def default(self, o):
        return o.__dict__


class TranslationStatisticsGenerator(object):

    # ----------------------------------------------------------------------
    def __init__(self, domain, source_path, destination_path, target_filename):
        self._domain = domain
        self._source_path = source_path
        self._destination_path = destination_path
        self._target_filename = target_filename
        self._pot_stats = None
        self._message_catalogs = None
        self._message_catalog = None
        self._overall_statistics = None

    # ----------------------------------------------------------------------
    def generate(self):
        self._update_pot_file()
        self._fetch_pot_stats()
        self._fetch_message_catalogs()
        for self._message_catalog in self._message_catalogs:
            self._update_message_catalog()
            self._fetch_message_catalog_stats()

        self._factor_overall_statistics()
        self._write_overall_statistics()

    # ----------------------------------------------------------------------
    def _update_pot_file(self):
        destination_filename = self._factor_pot_filename()
        update_pot_command = [
            'intltool-update',
            '--pot',
            '--gettext-package',
            self._domain,
            '--output-file',
            destination_filename]
        self._execute_command(update_pot_command)

    # ----------------------------------------------------------------------
    def _factor_pot_filename(self):
        return join(self._destination_path, '{}.pot'.format(self._domain))

    # ----------------------------------------------------------------------
    def _execute_command(self, command):
        environment = dict(
            srcdir=self._source_path,
            LANG='C')
        try:
            return check_output(
                command,
                env=environment,
                cwd=self._destination_path,
                stderr=STDOUT)
        except CalledProcessError as e:
            raise ValueError(
                'Command: "{}" exited with code {}: {}'.format(
                    command,
                    e.returncode,
                    e.output))

    # ----------------------------------------------------------------------
    def _fetch_pot_stats(self):
        self._pot_stats = self._read_po_translation_statistics(self._factor_pot_filename())

    # ----------------------------------------------------------------------
    def _read_po_translation_statistics(self, filename):
        msgfmt_command = ['msgfmt', '--statistics', filename]
        output = self._execute_command(msgfmt_command)
        # parse
        match = STATISTICS_REGEXP.match(output.decode('utf-8'))
        if match:
            translated = match.group('translated')
            fuzzy = match.group('fuzzy')
            untranslated = match.group('untranslated')
        else:
            raise ValueError('Unable to parse msgfmt output: {}'.format(output))

        return TranslationStatistics(
            translated=int(translated) if translated is not None else 0,
            fuzzy=int(fuzzy) if fuzzy is not None else 0,
            untranslated=int(untranslated) if untranslated is not None else 0)

    # ----------------------------------------------------------------------
    def _fetch_message_catalogs(self):
        self._message_catalogs = list()
        for po_filename in listdir(self._source_path):
            basename, extension = splitext(po_filename)
            if extension == '.po':
                last_translator = self._read_last_translator(po_filename)
                language_name = self._read_language_name(basename)

                message_catalog = MessageCatalog(
                    filename=po_filename,
                    last_translator=last_translator,
                    language_name=language_name,
                    language_code=basename)
                self._message_catalogs.append(message_catalog)

    # ----------------------------------------------------------------------
    def _read_last_translator(self, filename):
        filename = join(self._source_path, filename)
        with open(filename) as file_:
            for line in file_:
                if line.startswith('"Last-Translator:'):
                    match = LAST_TRANSLATOR_REGEXP.match(line)
                    if match:
                        return match.group('name').strip()
                    break
        return None

    # ----------------------------------------------------------------------
    def _read_language_name(self, locale):
        locale = Locale.parse(locale)
        return locale.get_display_name(locale='en')

    # ----------------------------------------------------------------------
    def _update_message_catalog(self):
        source_filename = join(self._source_path, self._message_catalog.filename)
        destination_filename = join(self._destination_path, self._message_catalog.filename)
        pot_file = self._factor_pot_filename()

        update_command = ['msgmerge', source_filename, pot_file, '--output-file', destination_filename]
        self._execute_command(update_command)

    # ----------------------------------------------------------------------
    def _fetch_message_catalog_stats(self):
        destination_filename = join(self._destination_path, self._message_catalog.filename)
        stats = self._read_po_translation_statistics(destination_filename)

        stats.percentage_translated = (stats.translated / self._pot_stats.untranslated) * 100
        stats.percentage_fuzzy = (stats.fuzzy / self._pot_stats.untranslated) * 100
        stats.percentage_untranslated = (stats.untranslated / self._pot_stats.untranslated) * 100

        self._message_catalog.statistics = stats

    # ----------------------------------------------------------------------
    def _factor_overall_statistics(self):
        self._overall_statistics = dict(
            total_statistics=self._pot_stats,
            catalog_statistics=self._message_catalogs)

        # add timestamp
        self._overall_statistics['generated_timestamp'] = time()

    # ----------------------------------------------------------------------
    def _write_overall_statistics(self):
        output_filename = join(self._destination_path, self._target_filename)
        with open(output_filename, 'w') as output_file:
            dump(self._overall_statistics, output_file, cls=SimpleObjectToJSONEncoder)