import {copyFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const source=new URL('../licenses/javascript/THIRD_PARTY_NOTICES.md',import.meta.url);
const destination=new URL('../product/frontend/dist/THIRD_PARTY_NOTICES.txt',import.meta.url);
await copyFile(fileURLToPath(source),fileURLToPath(destination));
