import test from 'node:test';
import assert from 'node:assert/strict';
import {win32} from 'node:path';
import {isContainedRelativePath} from '../main/game-data';

test('Windows game data cannot escape to another drive or UNC share', ()=>{
  for (const destination of ['D:\\other', 'C:\\outside', '\\\\server\\share\\data']) {
    const path = win32.relative('C:\\game', destination);
    assert.equal(isContainedRelativePath(path, win32.sep, win32.isAbsolute), false, destination);
  }
  for (const destination of ['C:\\game', 'C:\\game\\Data Files', 'C:\\game\\custom\\data']) {
    const path = win32.relative('C:\\game', destination);
    assert.equal(isContainedRelativePath(path, win32.sep, win32.isAbsolute), true, destination);
  }
});
