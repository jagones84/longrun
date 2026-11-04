#!/usr/bin/env bash
# The fix in flight (operator rule: TARGETED by default).
set -u
cd "$(dirname "$0")/.." || exit 1
export LONGRUN_BATTERY_TESTS="v795_steer_durable_visible v302_runtime_leak v674_send_idempotency v507_namespaced_subtools v442_abort_stop v364_queue_theme_links_ctx v773_live_choices_and_watcher_and_queue_edit v702_composer_stop_send v354_ui_links_pins v793_dsml_parameter_bleed v794_memory_workspace_scope v204_memory_governance v662_one_address_one_store v792_inject_identical_cap v791_invalid_reply_cap_config v458_compaction_model_vision v485_compaction_transcript"
exec bash tests/battery.sh
