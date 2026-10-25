/* DragSort — ONE pointer+touch reorder engine for Longrun list UIs.
 *
 * Shared by the Sessions sidebar (webui/index.html) and the Control agents
 * table (orbit.html): same hold-to-drag touch, same drop marks, same click
 * suppression, same server order contract (PATCH /api/sidebar/order).
 * Page-specific parts (what an item is, which group it is in, where the order
 * is persisted) stay in the page as small adapters — the state machine,
 * pointer capture, auto-scroll and touch handling live here exactly once.
 *
 * Usage:
 *   DragSort.bind(handleEl, {
 *     container,            // bounds element; targets are found inside it
 *     source,               // the item element being dragged
 *     id,                   // dragged id
 *     itemSel,              // selector for sibling items, e.g. ".sess[data-session-order-id]"
 *     idKey,                // dataset key holding the id, e.g. "sessionOrderId"
 *     grpKey,               // dataset key holding the group (omit for single-group lists)
 *     group,                // this drag's group value (compared against grpKey)
 *     measureSel,           // optional selector inside an item used for the
 *                           // before/after midpoint (defaults to the item itself)
 *     regionSel, regionKey, flatKey,
 *                           // region lists (sidebar): regionSel bounds the drop
 *                           // (e.g. ".sgroup-b"); regionKey is the dataset key
 *                           // on the region holding the group; flatKey is the
 *                           // dataset key on the container for ungrouped lists
 *     emptySel, emptyGrpKey,// optional placeholder selector (e.g. an empty-group
 *                           // row) that accepts an append drop; dataset key for its group
 *     scrollEl,             // optional scroll container auto-scrolled near edges
 *     isSaving,             // optional () => bool gate for concurrent saves
 *     onCommit,             // ({id, targetId, after}) => void on a real drop
 *   });
 *   // in the handle's click path:
 *   if (DragSort.consumeClick(e)) return;   // a drag just ended here
 */
(function (global) {
  "use strict";

  var HOLD_MS = 420;
  var MOVE_PX = 6;
  var TOUCH_MOVE_PX = 8;
  var SUPPRESS_MS = 700;
  var SCROLL_PAD = 28;
  var SCROLL_STEP = 12;

  var active = null;      // the one in-flight drag across the whole page
  var suppressed = null;  // {items, until} — clicks right after a drag die

  /* Pure reorder: move `id` before/after `targetId` (append when no target).
     The same function both pages use to build the PATCH body. */
  function moveItem(ids, id, targetId, after) {
    var next = (ids || []).filter(function (x) { return x !== id; });
    if (targetId === id) return (ids || []).slice();
    if (targetId && next.indexOf(targetId) !== -1) {
      next.splice(next.indexOf(targetId) + (after ? 1 : 0), 0, id);
    } else {
      next.push(id);
    }
    return next;
  }

  /* Stable order-by-stored-ids: pinned items first, then ranked items in
     stored sequence, then `fallback` order, then incoming order. The Sessions
     sidebar passes its system-session rule + sort as `isPinned`/`fallback`;
     the Control table passes neither (stored order, then current sort). */
  function orderByIds(items, ids, getId, fallback, isPinned) {
    var rank = new Map((ids || []).map(function (id, i) { return [id, i]; }));
    var original = new Map(items.map(function (item, i) { return [getId(item), i]; }));
    return items.slice().sort(function (a, b) {
      if (isPinned) {
        var pinned = (isPinned(a) ? 0 : 1) - (isPinned(b) ? 0 : 1);
        if (pinned) return pinned;
      }
      var ar = rank.has(getId(a)) ? rank.get(getId(a)) : Number.POSITIVE_INFINITY;
      var br = rank.has(getId(b)) ? rank.get(getId(b)) : Number.POSITIVE_INFINITY;
      if (ar !== br) return ar - br;
      return (fallback ? fallback(a, b) : 0) ||
        (original.get(getId(a)) - original.get(getId(b)));
    });
  }

  function clearMarks(root) {
    (root || document).querySelectorAll(".drop-before, .drop-after").forEach(function (el) {
      el.classList.remove("drop-before", "drop-after");
    });
  }

  function itemOf(o, node) {
    if (!node || !node.closest) return null;
    return node.closest(o.itemSel);
  }

  // A click landing on a just-dragged item (or its drop target) is the tail
  // of the drag, not a fresh click — swallow it for SUPPRESS_MS.
  function consumeClick(e) {
    if (!suppressed) return false;
    if (Date.now() > suppressed.until) { suppressed = null; return false; }
    var t = (e && e.target) || null;
    var hit = t && suppressed.items.some(function (item) {
      return item && (item === t || (item.contains && item.contains(t)));
    });
    if (!hit) return false;
    suppressed = null;
    if (e) { e.preventDefault(); e.stopPropagation(); }
    return true;
  }

  function setTarget(o, state, under, clientY) {
    clearMarks(o.container);
    var target = under && itemOf(o, under);
    state.valid = false;
    state.targetId = null;
    state.dropTarget = null;
    state.after = false;
    var sameGroup = function (el) {
      return !o.grpKey || !state.group ||
        (el && el.dataset && el.dataset[o.grpKey] === state.group);
    };
    if (target && o.container.contains(target) && sameGroup(target)) {
      state.valid = true;
      state.dropTarget = target;
      state.targetId = target.dataset[o.idKey];
      var measure = (o.measureSel && target.querySelector(o.measureSel)) || target;
      var r = measure.getBoundingClientRect();
      state.after = clientY >= r.top + r.height / 2;
      target.classList.add(state.after ? "drop-after" : "drop-before");
    } else if (under && o.container.contains(under)) {
      // No item under the pointer. Three page shapes, in order:
      // 1. region lists (sidebar): dropping on blank space appends when the
      //    enclosing region belongs to this drag's group (or when there is
      //    no region and the container's flat group matches);
      // 2. empty placeholders (orbit group tables): an empty-group row appends;
      // 3. plain containers: any position inside appends.
      if (o.regionSel) {
        var region = under.closest ? under.closest(o.regionSel) : null;
        if (o.regionKey || o.flatKey) {
          var rkey = region && o.regionKey ? region.dataset[o.regionKey] : undefined;
          var flat = o.flatKey ? o.container.dataset[o.flatKey] : undefined;
          if ((region && rkey === state.group) || (!region && flat === state.group)) {
            state.valid = true;
          }
        } else if (!region) {
          state.valid = true;
        }
      } else if (o.emptySel) {
        var empty = under.closest ? under.closest(o.emptySel) : null;
        if (empty && o.container.contains(empty) &&
            (!o.emptyGrpKey || !state.group ||
             (empty.dataset && empty.dataset[o.emptyGrpKey] === state.group))) {
          state.valid = true;
        }
      } else {
        state.valid = true;
      }
    }
    return state.valid;
  }

  function clearState(state) {
    if (state.holdTimer) clearTimeout(state.holdTimer);
    if (state.cleanup) state.cleanup();
    clearMarks(state.opts.container);
    if (state.source) state.source.classList.remove("dragging");
    if (active === state) active = null;
  }

  function moveDrag(o, state, x, y) {
    if (!state.live && Math.hypot(x - state.startX, y - state.startY) < MOVE_PX) return;
    state.live = true;
    state.suppressClick = true;
    state.source.classList.add("dragging");
    var sc = o.scrollEl, rr = sc && sc.getBoundingClientRect();
    if (rr && y < rr.top + SCROLL_PAD) sc.scrollTop -= SCROLL_STEP;
    else if (rr && y > rr.bottom - SCROLL_PAD) sc.scrollTop += SCROLL_STEP;
    setTarget(o, state, document.elementFromPoint(x, y), y);
  }

  function finishDrag(o, state) {
    if (active !== state) return;
    var dropTarget = state.dropTarget;
    clearState(state);
    if (state.suppressClick) {
      var items = [state.source, dropTarget].filter(function (item, i, all) {
        return item && all.indexOf(item) === i;
      });
      suppressed = { items: items, until: Date.now() + SUPPRESS_MS };
    }
    var move = state.live && state.valid && !!state.dropTarget && state.targetId !== state.id;
    var append = state.live && state.valid && !state.dropTarget;
    if (move) o.onCommit({ id: state.id, targetId: state.targetId, after: state.after });
    else if (append) o.onCommit({ id: state.id, targetId: null, after: true });
  }

  function bind(handle, o) {
    var begin = function (pointerId, pointerType, x, y) {
      if ((o.isSaving && o.isSaving()) || active || !o.source) return null;
      var state = {
        opts: o, id: o.id, group: o.group, source: o.source,
        pointerId: pointerId, pointerType: pointerType,
        startX: x, startY: y, live: false, armed: pointerType !== "touch",
        suppressClick: false, valid: false, targetId: null, dropTarget: null, after: false
      };
      active = state;
      state.holdTimer = setTimeout(function () {
        if (active !== state) return;
        state.suppressClick = true;
        if (pointerType === "touch") state.armed = true;
      }, HOLD_MS);
      return state;
    };
    handle.addEventListener("pointerdown", function (e) {
      if (e.pointerType === "touch" || (e.button !== undefined && e.button !== 0)) return;
      var state = begin(e.pointerId, e.pointerType, e.clientX, e.clientY);
      if (!state) return;
      try { handle.setPointerCapture(e.pointerId); } catch (_) {}
      var move = function (ev) {
        if (active !== state || !state.armed) return;
        moveDrag(o, state, ev.clientX, ev.clientY);
      };
      var up = function () { finishDrag(o, state); };
      var cancel = function () { if (active === state) clearState(state); };
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", up);
      handle.addEventListener("pointercancel", cancel);
      state.cleanup = function () {
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", up);
        handle.removeEventListener("pointercancel", cancel);
      };
    });
    handle.addEventListener("touchstart", function (e) {
      if (e.changedTouches.length !== 1) return;
      var touch = e.changedTouches[0];
      var state = begin(touch.identifier, "touch", touch.clientX, touch.clientY);
      if (!state) return;
      var byId = function (list) {
        return Array.prototype.find.call(list || [], function (t) {
          return t.identifier === state.pointerId;
        });
      };
      var move = function (ev) {
        var current = byId(ev.touches) || byId(ev.changedTouches);
        if (!current || active !== state) return;
        if (!state.armed) {
          if (Math.hypot(current.clientX - state.startX, current.clientY - state.startY) >= TOUCH_MOVE_PX) {
            if (active === state) clearState(state);
          }
          return;
        }
        ev.preventDefault();
        moveDrag(o, state, current.clientX, current.clientY);
      };
      var up = function () { finishDrag(o, state); };
      var cancel = function () { if (active === state) clearState(state); };
      document.addEventListener("touchmove", move, { passive: false });
      document.addEventListener("touchend", up, true);
      document.addEventListener("touchcancel", cancel, true);
      state.cleanup = function () {
        document.removeEventListener("touchmove", move);
        document.removeEventListener("touchend", up, true);
        document.removeEventListener("touchcancel", cancel, true);
      };
    }, { passive: true });
  }

  global.DragSort = {
    HOLD_MS: HOLD_MS,
    moveItem: moveItem,
    orderByIds: orderByIds,
    clearMarks: clearMarks,
    consumeClick: consumeClick,
    bind: bind
  };
})(window);
