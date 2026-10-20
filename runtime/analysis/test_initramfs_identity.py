import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest

from initramfs_identity import verify_image


class InitramfsIdentity(unittest.TestCase):
    def archive(self, root, names):
        image = root / 'image.cpio'
        data = subprocess.run(['cpio', '--null', '-o', '-H', 'newc', '--quiet'],
                              input=b''.join(('./' + name).encode() + b'\0' for name in names),
                              cwd=root, capture_output=True, check=True).stdout
        image.write_bytes(data)
        return image

    def fixture(self, root):
        files = {'simulation/menu-observe.so': b'current observer',
                 'simulation/pin-control-probe': b'current probe',
                 'usr/lib/appFw.so': b'original library'}
        for name, data in files.items():
            path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
        return {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}

    def test_actual_newc_and_each_identity_mismatch(self):
        for changed in (None, 'simulation/menu-observe.so', 'simulation/pin-control-probe', 'usr/lib/appFw.so'):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); expected = self.fixture(root)
                if changed:
                    (root / changed).write_bytes(b'older image content')
                image = self.archive(root, expected)
                if changed:
                    with self.assertRaisesRegex(ValueError, 'content differs'):
                        verify_image(image, expected)
                else:
                    self.assertEqual(verify_image(image, expected), expected)

    def test_missing_duplicate_symlink_and_truncated_images(self):
        for kind in ('missing', 'duplicate', 'symlink', 'symlink-alias', 'late-symlink-alias', 'truncated', 'extra-archive'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); expected = self.fixture(root); names = list(expected)
                if kind == 'missing':
                    names.pop()
                if kind == 'duplicate':
                    names.append(names[0])
                if kind == 'symlink':
                    (root / names[0]).unlink(); (root / names[0]).symlink_to('../usr/lib/appFw.so')
                if kind in ('symlink-alias', 'late-symlink-alias'):
                    (root / 'alias').symlink_to('usr/lib',target_is_directory=True)
                    names += ['alias', 'alias/appFw.so'] if kind == 'symlink-alias' else ['alias/appFw.so', 'alias']
                image = self.archive(root, names)
                if kind == 'truncated':
                    image.write_bytes(image.read_bytes()[:140])
                if kind == 'extra-archive':
                    image.write_bytes(image.read_bytes() + image.read_bytes())
                with self.assertRaises(ValueError):
                    verify_image(image, expected)


if __name__ == '__main__':
    unittest.main()
