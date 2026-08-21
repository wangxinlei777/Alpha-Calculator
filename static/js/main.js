const bootstrapModal = new bootstrap.Modal(document.getElementById('editModal'));

        function showLoading() {
            document.getElementById('loader').style.display = 'flex';
        }

        function submitMainForm() {
            showLoading();
            document.getElementById('mainForm').submit();
        }

        function toggleAll(el) {
            const checkboxes = document.querySelectorAll('.row-checkbox');
            checkboxes.forEach(cb => cb.checked = el.checked);
            submitMainForm();
        }

        let displayMode = window.__DISPLAY_MODE__;
        function toggleDisplayMode() {
            const input = document.getElementById('displayModeInput');
            displayMode = (displayMode === 'all') ? 'selected_only' : 'all';
            input.value = displayMode;
            submitMainForm();
        }

        function openEditModal(name, paramsJson) {
            const params = JSON.parse(paramsJson);
            document.getElementById('modalItemName').innerText = name;
            document.getElementById('editItemName').value = name;

            for (let key in params) {
                const input = document.getElementById('m_' + key);
                if (input) input.value = params[key];
            }
            bootstrapModal.show();
        }

        async function saveOverride() {
            const name = document.getElementById('editItemName').value;
            const params = {
                B_BOOK: parseFloat(document.getElementById('m_B_BOOK').value),
                B_SALE: parseFloat(document.getElementById('m_B_SALE').value),
                K_BOOK_PROFIT: parseFloat(document.getElementById('m_K_BOOK_PROFIT').value),
                K_SALE_PROFIT: parseFloat(document.getElementById('m_K_SALE_PROFIT').value),
                K_BOOK_ACTIVE: parseFloat(document.getElementById('m_K_BOOK_ACTIVE').value),
                K_SALE_ACTIVE: parseFloat(document.getElementById('m_K_SALE_ACTIVE').value),
                K_BOOK_STOCK: parseFloat(document.getElementById('m_K_BOOK_STOCK').value),
                K_SALE_STOCK: parseFloat(document.getElementById('m_K_SALE_STOCK').value),
                K_BOOK_BRAND: parseFloat(document.getElementById('m_K_BOOK_BRAND').value),
                K_SALE_BRAND: parseFloat(document.getElementById('m_K_SALE_BRAND').value)
            };

            await fetch('/api/save_override', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ name, params })
            });

            bootstrapModal.hide();
            showLoading();
            document.querySelector('#mainForm').submit();
        }

        async function resetOverride() {
            const name = document.getElementById('editItemName').value;
            await fetch('/api/reset_override', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ name })
            });

            bootstrapModal.hide();
            showLoading();
            document.querySelector('#mainForm').submit();
        }

        /* ================= 周期走势 ================= */
        let historyData = { records: [] };
        let historyCharts = {};

        function esc(s) {
            const d = document.createElement('div');
            d.textContent = (s == null) ? '' : String(s);
            return d.innerHTML;
        }

        function numFmt(n) {
            if (n == null || isNaN(n)) return '0';
            return Number(n).toLocaleString('zh-CN', {maximumFractionDigits: 0});
        }

        function round2(v) {
            return (v == null) ? null : Math.round(v * 100) / 100;
        }

        function showToast(msg, type) {
            const box = document.getElementById('toastBox');
            const t = document.createElement('div');
            const cls = type === 'danger' ? 'danger' : (type === 'warning' ? 'warning' : 'success');
            t.className = 'toast align-items-center text-bg-' + cls + ' border-0 show';
            t.innerHTML = '<div class="d-flex"><div class="toast-body">' + esc(msg) +
                '</div><button type="button" class="btn-close btn-close-white me-2 m-auto" onclick="this.closest(\'.toast\').remove()"></button></div>';
            box.appendChild(t);
            setTimeout(() => { t.remove(); }, 5000);
        }

        async function loadHistory() {
            try {
                const res = await fetch('/api/history');
                historyData = await res.json();
            } catch (e) {
                historyData = { records: [] };
            }
            renderHistoryList();
        }

        function renderHistoryList() {
            const list = document.getElementById('historyList');
            const recs = historyData.records || [];
            list.innerHTML = '';
            if (!recs.length) {
                list.innerHTML = '<div class="text-muted text-center py-4"><i class="bi bi-inbox me-1"></i>暂无历史记录</div>';
            } else {
                recs.slice().sort((a, b) => b.id - a.id).forEach(r => {
                    const itemCount = (r.items || []).length;
                    const pool = r.pool || {};
                    const div = document.createElement('div');
                    div.className = 'card mb-2 border draggable-item';
                    div.draggable = true;
                    div.setAttribute('title', '拖拽到右侧图表区进行对比');
                    div.addEventListener('dragstart', function (e) {
                        e.dataTransfer.setData('text/plain', String(r.id));
                        e.dataTransfer.effectAllowed = 'copy';
                    });
                    div.innerHTML = `<div class="card-body py-2 px-3 d-flex align-items-center gap-2">
                        <i class="bi bi-grip-vertical text-muted drag-handle"></i>
                        <div class="me-auto">
                            <strong>${esc(r.name)}</strong>
                            <small class="text-muted d-block">${esc(r.created_at)} · ${itemCount} 个品规 · 池差额 ${numFmt(pool.pool_total)}</small>
                        </div>
                        <button class="btn btn-sm btn-outline-secondary" onclick="renameRecord(${r.id})" title="重命名该周期">
                            <i class="bi bi-pencil"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-danger" onclick="deleteRecord(${r.id})" title="删除该周期">
                            <i class="bi bi-trash"></i>
                        </button>
                    </div>`;
                    list.appendChild(div);
                });
            }

            // 已拖入图表区的记录若被删除/失效，则自动移除
            if (chartRecordIds.some(id => !recs.some(r => r.id === id))) {
                chartRecordIds = chartRecordIds.filter(id => recs.some(r => r.id === id));
                selectedSpecs = selectedSpecs.filter(s => unionSpecs().includes(s));
                renderChips();
                renderSpecFilters();
                if (chartRecordIds.length) renderCharts(); else destroyAllCharts();
            }
        }

        function destroyChart(canvasId) {
            if (historyCharts[canvasId]) {
                historyCharts[canvasId].destroy();
                delete historyCharts[canvasId];
            }
        }

        function makeLineChart(canvasId, labels, datasets) {
            destroyChart(canvasId);
            historyCharts[canvasId] = new Chart(document.getElementById(canvasId).getContext('2d'), {
                type: 'line',
                data: {labels: labels, datasets: datasets.map(d => ({
                    label: d.label,
                    data: d.data,
                    borderColor: d.color,
                    backgroundColor: d.color,
                    borderWidth: (d.borderWidth != null) ? d.borderWidth : 2,
                    tension: 0.3,
                    pointRadius: (d.pointRadius != null) ? d.pointRadius : 4,
                    spanGaps: true,
                    borderDash: d.dashed ? [6, 4] : [],
                    pointStyle: d.dashed ? 'rectRot' : 'circle'
                }))},
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: {mode: 'index', intersect: false},
                    plugins: {legend: {position: 'bottom', labels: {boxWidth: 12, font: {size: 11}}}},
                    scales: {y: {beginAtZero: true}}
                }
            });
        }

        function renderCharts() {
            const recs = sortedRecords();
            const specs = selectedSpecs;
            if (!recs.length || !specs.length) { destroyAllCharts(); return; }
            const labels = recs.map(r => esc(r.name));

            const poolDatasets = [
                {label: '总预订积分', data: recs.map(r => (r.pool || {}).pool_book), color: '#1f5aa8'},
                {label: '总销售积分', data: recs.map(r => (r.pool || {}).pool_sale), color: '#1e7e34'},
                {label: '积分差额', data: recs.map(r => (r.pool || {}).pool_total), color: '#d97706', dashed: true}
            ];
            makeLineChart('chartPoints', labels, poolDatasets);

            const specDatasets = [];
            specs.forEach(s => {
                const c = colorFor(s);
                specDatasets.push({label: s + ' · 预订', data: recs.map(r => specValue(r, s, '最终预订积分')), color: c});
                specDatasets.push({label: s + ' · 销售', data: recs.map(r => specValue(r, s, '最终销售积分')), color: c, dashed: true});
            });
            makeLineChart('chartSpecs', labels, specDatasets);

            makeLineChart('chartFactors', labels, [
                {label: '盈利因子', data: recs.map(r => avgOfSpecs(r, specs, 'F_profit_book')), color: '#1f5aa8'},
                {label: '活跃因子', data: recs.map(r => avgOfSpecs(r, specs, 'F_active_book')), color: '#d97706'},
                {label: '库存因子', data: recs.map(r => avgOfSpecs(r, specs, 'F_stock_book')), color: '#1e7e34'},
                {label: '品牌因子', data: recs.map(r => avgOfSpecs(r, specs, 'F_brand_book')), color: '#c0392b'}
            ]);
        }

        /* ---- 拖拽对比逻辑 ---- */
        let chartRecordIds = [];
        let selectedSpecs = [];
        const SPEC_PALETTE = ['#1f5aa8', '#d97706', '#1e7e34', '#c0392b', '#6f42c1', '#0d6e6e', '#945b27', '#7f5539'];

        function hashStr(s) {
            let h = 0;
            for (const c of String(s)) h = (h * 31 + c.codePointAt(0)) >>> 0;
            return h;
        }

        function colorFor(spec) {
            return SPEC_PALETTE[hashStr(spec) % SPEC_PALETTE.length];
        }

        function sortedRecords() {
            return chartRecordIds
                .map(id => (historyData.records || []).find(r => r.id === id))
                .filter(Boolean)
                .sort((a, b) => (a.created_at < b.created_at) ? -1 : (a.created_at > b.created_at) ? 1 : (a.id - b.id));
        }

        function unionSpecs() {
            const set = new Set();
            sortedRecords().forEach(r => (r.items || []).forEach(it => set.add(it['卷烟规格'])));
            return [...set].sort();
        }

        function specValue(r, spec, key) {
            const it = (r.items || []).find(i => i['卷烟规格'] === spec);
            return it ? it[key] : null;
        }

        function avgOfSpecs(r, specs, key) {
            let sum = 0, n = 0;
            specs.forEach(s => {
                const v = specValue(r, s, key);
                if (v != null && !isNaN(v)) { sum += Number(v); n++; }
            });
            return n ? round2(sum / n) : null;
        }

        function addRecordToCharts(id) {
            if (!(historyData.records || []).some(r => r.id === id)) return;
            if (!chartRecordIds.includes(id)) chartRecordIds.push(id);
            // 新拖入记录中的品规自动加入筛选（可手动取消）
            selectedSpecs = [...new Set([...selectedSpecs, ...unionSpecs()])];
            renderChips();
            renderSpecFilters();
            renderCharts();
        }

        function removeRecordFromCharts(id) {
            chartRecordIds = chartRecordIds.filter(x => x !== id);
            selectedSpecs = selectedSpecs.filter(s => unionSpecs().includes(s));
            renderChips();
            renderSpecFilters();
            if (chartRecordIds.length) renderCharts(); else destroyAllCharts();
        }

        function clearChartRecords() {
            chartRecordIds = [];
            selectedSpecs = [];
            renderChips();
            renderSpecFilters();
            destroyAllCharts();
        }

        function destroyAllCharts() {
            ['chartPoints', 'chartSpecs', 'chartFactors'].forEach(id => destroyChart(id));
        }

        function renderChips() {
            const box = document.getElementById('chartRecords');
            const hint = document.getElementById('chartEmptyHint');
            const row = document.getElementById('chartRow');
            const clearBtn = document.getElementById('clearChartsBtn');
            box.innerHTML = '';
            if (!chartRecordIds.length) {
                hint.style.display = 'block';
                row.style.display = 'none';
                clearBtn.style.display = 'none';
                renderParamTable('');
                return;
            }
            hint.style.display = 'none';
            row.style.display = '';
            clearBtn.style.display = '';
            sortedRecords().forEach(r => {
                const chip = document.createElement('span');
                chip.className = 'record-chip';
                chip.innerHTML = `<i class="bi bi-calendar2 text-primary"></i> ${esc(r.name)}
                    <button type="button" class="chip-remove" title="移出对比" onclick="removeRecordFromCharts(${r.id})"><i class="bi bi-x"></i></button>`;
                box.appendChild(chip);
            });
            renderParamTable('');
        }

        function renderSpecFilters() {
            const box = document.getElementById('specFilterBox');
            const hint = document.getElementById('specFilterHint');
            box.innerHTML = '';
            const specs = unionSpecs();
            hint.style.display = selectedSpecs.length ? 'none' : 'inline';
            specs.forEach(s => {
                const on = selectedSpecs.includes(s);
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'btn btn-sm ' + (on ? 'btn-primary' : 'btn-outline-secondary');
                btn.setAttribute('style', '--bs-btn-padding-y:0.15rem;');
                btn.innerHTML = `<span class="me-1" style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${colorFor(s)}"></span>${esc(s)}`;
                btn.onclick = () => toggleSpec(s);
                box.appendChild(btn);
            });
        }

        function toggleSpec(s) {
            selectedSpecs = selectedSpecs.includes(s) ? selectedSpecs.filter(x => x !== s) : [...selectedSpecs, s];
            renderSpecFilters();
            renderCharts();
        }

        function selectAllSpecs() {
            selectedSpecs = unionSpecs();
            renderSpecFilters();
            renderCharts();
        }

        function clearSpecs() {
            selectedSpecs = [];
            renderSpecFilters();
            renderCharts();
        }

        /* ---- 调权参数在各周期变化 ---- */
        const PARAM_KEYS = ['B_BOOK', 'B_SALE',
            'K_BOOK_PROFIT', 'K_SALE_PROFIT', 'K_BOOK_ACTIVE', 'K_SALE_ACTIVE',
            'K_BOOK_STOCK', 'K_SALE_STOCK', 'K_BOOK_BRAND', 'K_SALE_BRAND'];

        function itemOf(r, spec) {
            return (r.items || []).find(i => i['卷烟规格'] === spec) || null;
        }

        function renderParamTable(spec) {
            const sel = document.getElementById('paramSpecSelect');
            const tbody = document.getElementById('paramTableBody');
            if (!sel) return;
            const specs = unionSpecs();
            const cur = spec || (specs.includes(sel.value) ? sel.value : specs[0]) || '';
            sel.innerHTML = '';
            specs.forEach(s => {
                const o = document.createElement('option');
                o.value = s;
                o.textContent = s;
                sel.appendChild(o);
            });
            sel.value = cur;
            tbody.innerHTML = '';
            if (!cur) return;

            sortedRecords().forEach(r => {
                const it = itemOf(r, cur);
                const tr = document.createElement('tr');
                if (!it) {
                    tr.innerHTML = '<td>' + esc(r.name) + '</td><td class="text-muted">—</td><td class="text-muted">—</td><td class="text-muted">—</td><td class="text-muted">—</td><td class="text-muted">—</td><td class="text-muted">—</td><td class="text-muted">—</td><td class="text-muted">—</td><td class="text-muted">—</td><td class="text-muted">—</td><td class="text-muted">—</td>';
                    tbody.appendChild(tr);
                    return;
                }
                let up = {};
                try { up = JSON.parse(it['used_params'] || '{}'); } catch (e) { up = {}; }
                const ov = it['is_overridden']
                    ? '<span class="badge bg-warning text-dark">已调权</span>'
                    : '<span class="text-muted">全局</span>';
                let cells = '<td>' + esc(r.name) + '</td><td>' + ov + '</td>';
                PARAM_KEYS.forEach(k => {
                    cells += '<td class="text-end">' + (up[k] != null ? up[k] : '—') + '</td>';
                });
                tr.innerHTML = cells;
                tbody.appendChild(tr);
            });
        }

        /* ---- 拖放事件 ---- */
        (function initDropZone() {
            const zone = document.getElementById('chartDropZone');
            if (!zone) return;
            zone.addEventListener('dragover', function (e) {
                if (e.dataTransfer.types.includes('text/plain')) {
                    e.preventDefault();
                    zone.classList.add('drop-over');
                }
            });
            zone.addEventListener('dragleave', function () {
                zone.classList.remove('drop-over');
            });
            zone.addEventListener('drop', function (e) {
                e.preventDefault();
                zone.classList.remove('drop-over');
                const id = parseInt(e.dataTransfer.getData('text/plain'), 10);
                if (!isNaN(id)) addRecordToCharts(id);
            });
        })();

        async function saveCurrentPeriod() {
            const name = document.getElementById('periodName').value.trim();
            const btn = document.getElementById('savePeriodBtn');
            btn.disabled = true;
            const originalHtml = btn.innerHTML;
            btn.innerHTML = '<i class="bi bi-arrow-clockwise bi-spin me-1"></i> 保存中';
            try {
                const res = await fetch('/api/save_history', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({name: name})
                });
                const data = await res.json();
                if (data.status === 'success') {
                    if (data.duplicate) {
                        showToast('该计算结果此前已存档（周期：' + data.record.name + '），未重复保存', 'warning');
                    } else {
                        showToast('已保存历史周期：' + data.record.name, 'success');
                        document.getElementById('periodName').value = '';
                    }
                    renderHistoryList();
                } else {
                    showToast(data.message || '保存失败', 'danger');
                }
            } catch (e) {
                showToast('保存失败：' + e.message, 'danger');
            }
            btn.disabled = false;
            btn.innerHTML = originalHtml;
        }

        async function renameRecord(id) {
            const rec = (historyData.records || []).find(r => r.id === id);
            if (!rec) return;
            const name = prompt('请输入新的周期名称：', rec.name);
            if (name === null || name.trim() === '' || name.trim() === rec.name) return;
            try {
                const res = await fetch('/api/history/' + id + '/rename', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({name: name.trim()})
                });
                const data = await res.json();
                if (data.status === 'success') {
                    showToast('已重命名周期', 'success');
                    await loadHistory();
                    renderChips();
                    renderSpecFilters();
                    renderCharts();
                } else {
                    showToast(data.message || '重命名失败', 'danger');
                }
            } catch (e) {
                showToast('重命名失败：' + e.message, 'danger');
            }
        }

        async function deleteRecord(id) {
            if (!confirm('确定删除该历史周期记录？')) return;
            try {
                const res = await fetch('/api/history/' + id, {method: 'DELETE'});
                if (res.ok) {
                    showToast('已删除历史周期', 'success');
                    loadHistory();
                } else {
                    showToast('删除失败', 'danger');
                }
            } catch (e) {
                showToast('删除失败：' + e.message, 'danger');
            }
        }

        /* ================= 两期对比 ================= */
        function cmpRecs() {
            return (historyData.records || []).slice().sort((a, b) =>
                (a.created_at < b.created_at) ? -1 : (a.created_at > b.created_at) ? 1 : (a.id - b.id));
        }

        function populateCompare() {
            const selA = document.getElementById('cmpA');
            const selB = document.getElementById('cmpB');
            const recs = cmpRecs();
            selA.innerHTML = '';
            selB.innerHTML = '';
            recs.forEach(r => {
                const oA = document.createElement('option');
                oA.value = r.id;
                oA.textContent = r.name + '（' + r.created_at + '）';
                selA.appendChild(oA);
                const oB = oA.cloneNode(true);
                selB.appendChild(oB);
            });
            if (recs.length >= 2) {
                selA.value = recs[recs.length - 2].id;
                selB.value = recs[recs.length - 1].id;
            } else if (recs.length === 1) {
                selA.value = selB.value = recs[0].id;
            }
            renderCompare();
        }

        function recById(id) {
            return (historyData.records || []).find(r => r.id === Number(id)) || null;
        }

        function diffCell(a, b) {
            if (a == null || b == null) return '<td class="text-end text-muted">—</td>';
            const d = Number(b) - Number(a);
            const cls = d > 0 ? 'style="color:var(--bad);"' : (d < 0 ? 'style="color:var(--ok);"' : '');
            return `<td class="text-end ${cls ? '' : ''}" ${cls}>${d > 0 ? '+' : ''}${numFmt(d)}</td>`;
        }

        function renderCompare() {
            const A = recById(document.getElementById('cmpA').value);
            const B = recById(document.getElementById('cmpB').value);
            const empty = document.getElementById('cmpEmpty');
            const wrap = document.getElementById('cmpTableWrap');
            const summaryBox = document.getElementById('cmpSummary');
            const tbody = document.getElementById('cmpBody');

            if (!A || !B) {
                empty.style.display = 'block';
                wrap.style.display = 'none';
                summaryBox.innerHTML = '';
                return;
            }
            empty.style.display = 'none';
            wrap.style.display = '';
            tbody.innerHTML = '';

            const itemsA = A.items || [], itemsB = B.items || [];
            const byName = {};
            itemsA.forEach(it => { byName[it['卷烟规格']] = {a: it}; });
            itemsB.forEach(it => {
                byName[it['卷烟规格']] = byName[it['卷烟规格']] || {};
                byName[it['卷烟规格']].b = it;
            });

            const rows = Object.keys(byName).map(name => {
                const a = byName[name].a || null;
                const b = byName[name].b || null;
                return {
                    name: name,
                    aBook: a ? a['最终预订积分'] : null,
                    bBook: b ? b['最终预订积分'] : null,
                    aSale: a ? a['最终销售积分'] : null,
                    bSale: b ? b['最终销售积分'] : null
                };
            });
            rows.sort((x, y) => {
                const dx = (x.aBook != null && x.bBook != null) ? Math.abs(x.bBook - x.aBook) : 0;
                const dy = (y.aBook != null && y.bBook != null) ? Math.abs(y.bBook - y.aBook) : 0;
                return dy - dx;
            });

            rows.forEach(row => {
                const tr = document.createElement('tr');
                tr.innerHTML = `<td>${esc(row.name)}</td>
                    <td class="text-end">${row.aBook != null ? row.aBook : '—'}</td>
                    <td class="text-end">${row.bBook != null ? row.bBook : '—'}</td>
                    ${diffCell(row.aBook, row.bBook)}
                    <td class="text-end">${row.aSale != null ? row.aSale : '—'}</td>
                    <td class="text-end">${row.bSale != null ? row.bSale : '—'}</td>
                    ${diffCell(row.aSale, row.bSale)}`;
                tbody.appendChild(tr);
            });

            const aPool = A.pool || {}, bPool = B.pool || {};
            const dTotal = (bPool.pool_total != null && aPool.pool_total != null)
                ? Number(bPool.pool_total) - Number(aPool.pool_total) : null;
            summaryBox.innerHTML = `
                <div class="col-md-4">
                    <div class="stat-card">
                        <div class="stat-label">${esc(A.name)} 池差额</div>
                        <div class="stat-value" style="font-size:20px;">${aPool.pool_total != null ? numFmt(aPool.pool_total) : '—'}</div>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="stat-card">
                        <div class="stat-label">${esc(B.name)} 池差额</div>
                        <div class="stat-value" style="font-size:20px;">${bPool.pool_total != null ? numFmt(bPool.pool_total) : '—'}</div>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="stat-card ${dTotal != null && dTotal > 0 ? 'bad' : 'good'}">
                        <div class="stat-label">池差额变化（B - A）</div>
                        <div class="stat-value" style="font-size:20px;">${dTotal != null ? (dTotal > 0 ? '+' : '') + numFmt(dTotal) : '—'}</div>
                    </div>
                </div>`;
        }

        document.getElementById('history-tab').addEventListener('shown.bs.tab', loadHistory);
        document.getElementById('compare-tab').addEventListener('shown.bs.tab', async function () {
            if (!historyData.records.length) {
                await loadHistory();
            }
            populateCompare();
        });
        document.getElementById('admin-tab').addEventListener('shown.bs.tab', function () {
            loadAudit(1);
            loadUsers();
        });

/* ================= 因子构成拆解 ================= */
        const breakdownModal = new bootstrap.Modal(document.getElementById('breakdownModal'));
        const CURRENT_ROLE = window.__CURRENT_ROLE__;

        function jsq(s) {
            return String(s == null ? '' : s).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
        }

        function bdFmt(v) {
            if (v == null || isNaN(v)) return '—';
            return (Math.abs(v - Math.round(v)) < 1e-9) ? String(Math.round(v)) : Number(v).toFixed(2);
        }

        function bdRows(b) {
            const rows = [
                ['基准分', b.base, null],
                ['＋ 盈利因子贡献', b.profit, b.factors && b.factors.profit],
                ['＋ 活跃因子贡献', b.active, b.factors && b.factors.active],
                ['＋ 库存因子贡献', b.stock, b.factors && b.factors.stock],
                ['＋ 品牌因子贡献', b.brand, b.factors && b.factors.brand],
                ['＝ 原始积分', b.raw, null],
                ['取整/封顶后最终积分', b.final, null],
            ];
            return rows.map(function (r) {
                return `<tr><td class="text-start">${esc(r[0])}</td><td class="fw-bold">${bdFmt(r[1])}</td><td>${r[2] != null ? bdFmt(r[2]) : '—'}</td></tr>`;
            }).join('');
        }

        function openBreakdown(name, jsonStr) {
            document.getElementById('bdItemName').innerText = name;
            try {
                const bd = JSON.parse(jsonStr || '{}');
                document.getElementById('bdBookBody').innerHTML = bdRows(bd.book || {});
                document.getElementById('bdSaleBody').innerHTML = bdRows(bd.sale || {});
            } catch (e) {
                document.getElementById('bdBookBody').innerHTML = '<tr><td colspan="3" class="text-muted text-center">该周期数据未包含拆解信息</td></tr>';
                document.getElementById('bdSaleBody').innerHTML = '';
            }
            breakdownModal.show();
        }

        /* ================= 投放优化建议 ================= */
        async function suggestBaseline() {
            const target = parseFloat(document.getElementById('suggestTarget').value) || 0;
            const box = document.getElementById('suggestResult');
            box.innerHTML = '<div class="text-muted small"><i class="bi bi-arrow-clockwise bi-spin me-1"></i>正在求解目标差额，请稍候...</div>';
            const res = await fetch('/api/suggest/baseline', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({target: target})
            });
            const data = await res.json();
            if (data.status !== 'success') {
                box.innerHTML = `<div class="alert alert-warning py-2 small">${esc(data.message || '求解失败')}</div>`;
                return;
            }
            box.innerHTML = `
                <div class="stat-card mb-2">
                    <div class="stat-label">建议基准预订积分 B_BOOK（目标池差额 ${target > 0 ? '+' : ''}${numFmt(target)}）</div>
                    <div class="stat-value" style="color:var(--primary);">${data.b_book}</div>
                    <div class="text-muted small mt-1">按此基准试算，池差额约为
                        <b style="color:${data.achieved_diff >= 0 ? 'var(--ok)' : 'var(--bad)'};">${data.achieved_diff > 0 ? '+' : ''}${numFmt(data.achieved_diff)}</b>
                    </div>
                    <button type="button" class="btn btn-sm btn-primary mt-2" onclick="applyBaseline(${data.b_book})">
                        <i class="bi bi-arrow-down-up me-1"></i> 填入左侧表单并计算
                    </button>
                </div>`;
        }

        function applyBaseline(b) {
            const el = document.querySelector('[name="B_BOOK"]');
            if (el) el.value = b;
            showToast('已填入基准预订积分：' + b + '，请点击「开始计算」', 'success');
        }

        async function suggestAdjust() {
            const target = parseFloat(document.getElementById('suggestTarget').value) || 0;
            const max_ratio = (parseFloat(document.getElementById('suggestRatio').value) || 30) / 100;
            const box = document.getElementById('suggestResult');
            box.innerHTML = '<div class="text-muted small"><i class="bi bi-arrow-clockwise bi-spin me-1"></i>正在生成投放量调整建议，请稍候...</div>';
            const res = await fetch('/api/suggest/adjust', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({target: target, max_ratio: max_ratio})
            });
            const data = await res.json();
            if (data.status !== 'success') {
                box.innerHTML = `<div class="alert alert-warning py-2 small">${esc(data.message || '生成失败')}</div>`;
                return;
            }
            let html = `
                <div class="d-flex flex-wrap gap-2 mb-2 small">
                    <span class="record-chip">目标差额 ${target > 0 ? '+' : ''}${numFmt(target)}</span>
                    <span class="record-chip">需${data.direction === 1 ? '增加' : '减少'}预订积分 ${numFmt(data.need)}</span>
                    <span class="record-chip">可覆盖 ${numFmt(data.covered)}</span>
                    <span class="record-chip ${data.feasible ? '' : 'text-danger'}">${data.feasible ? '建议可完全达成目标' : '受调整上限约束，无法完全达成'}</span>
                    <span class="record-chip">调整后投影池差额 ${data.new_diff > 0 ? '+' : ''}${numFmt(data.new_diff)}</span>
                </div>
                <div class="table-responsive">
                <table class="table table-sm table-bordered align-middle" style="font-size:12px;">
                    <thead><tr>
                        <th>品规</th><th class="text-end">当前箱数</th><th class="text-end">建议箱数</th>
                        <th class="text-end">调整量</th><th class="text-end">影响总预订积分</th><th class="text-end">预订积分</th>
                    </tr></thead><tbody>`;
            data.rows.forEach(r => {
                if (Math.abs(r.delta_box) < 0.01) return;
                html += `<tr>
                    <td>${esc(r.name)}</td>
                    <td class="text-end">${numFmt(r.box)}</td>
                    <td class="text-end fw-bold">${numFmt(r.suggest_box)}</td>
                    <td class="text-end" style="color:${r.delta_box > 0 ? 'var(--bad)' : 'var(--ok)'};">${r.delta_box > 0 ? '+' : ''}${r.delta_box.toFixed(1)}</td>
                    <td class="text-end" style="color:${r.impact > 0 ? 'var(--bad)' : 'var(--ok)'};">${r.impact > 0 ? '+' : ''}${numFmt(r.impact)}</td>
                    <td class="text-end">${r.book}</td>
                </tr>`;
            });
            html += `</tbody></table></div>
                <small class="text-muted"><i class="bi bi-info-circle me-1"></i>红字为增加投放（预订积分上升），绿字为缩减投放；建议仅供参考，请结合零售户市场实际确定最终投放量。</small>`;
            box.innerHTML = html;
        }

        /* ================= 操作审计日志 ================= */
        let auditPage = 1;
        let auditActionsCache = [];

        async function loadAudit(page) {
            auditPage = page || 1;
            const user = document.getElementById('auditUser').value.trim();
            const action = document.getElementById('auditAction').value;
            const url = '/api/audit?page=' + auditPage + '&per_page=30'
                + (user ? '&user=' + encodeURIComponent(user) : '')
                + (action ? '&action=' + encodeURIComponent(action) : '');
            const res = await fetch(url);
            const data = await res.json();
            const body = document.getElementById('auditBody');
            body.innerHTML = '';
            if (!data.logs.length) {
                body.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-4">暂无日志记录</td></tr>';
            }
            data.logs.forEach(l => {
                const tr = document.createElement('tr');
                tr.innerHTML = `<td class="text-muted">${esc(l.ts)}</td><td>${esc(l.user)}</td>
                    <td><span class="badge bg-light border text-dark">${esc(l.action)}</span></td>
                    <td>${esc(l.detail)}</td><td class="text-muted">${esc(l.ip || '')}</td>`;
                body.appendChild(tr);
            });
            const totalPages = Math.ceil(data.total / data.per_page) || 1;
            document.getElementById('auditInfo').textContent = '共 ' + data.total + ' 条，第 ' + auditPage + '/' + totalPages + ' 页';
            document.getElementById('auditPrev').disabled = auditPage <= 1;
            document.getElementById('auditNext').disabled = auditPage >= totalPages;
            if (!auditActionsCache.length && data.actions && data.actions.length) {
                auditActionsCache = data.actions;
                const sel = document.getElementById('auditAction');
                auditActionsCache.forEach(a => {
                    const o = document.createElement('option');
                    o.value = a;
                    o.textContent = a;
                    sel.appendChild(o);
                });
            }
        }

        function resetAuditFilter() {
            document.getElementById('auditUser').value = '';
            document.getElementById('auditAction').value = '';
            loadAudit(1);
        }

        async function clearAudit() {
            if (!confirm('确定清空全部操作日志？此操作不可撤销。')) return;
            const res = await fetch('/api/audit', {method: 'DELETE'});
            const data = await res.json();
            if (data.status === 'success') { showToast('操作日志已清空', 'success'); loadAudit(1); }
        }

        /* ================= 用户管理 ================= */
        async function loadUsers() {
            const body = document.getElementById('userBody');
            if (!body) return;
            const res = await fetch('/api/users');
            const data = await res.json();
            body.innerHTML = '';
            if (!data.users || !data.users.length) {
                body.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-3">暂无用户</td></tr>';
                return;
            }
            data.users.forEach(u => {
                const roleName = u.role === 'admin' ? '管理员' : (u.role === 'operator' ? '操作员' : '只读');
                const tr = document.createElement('tr');
                tr.innerHTML = `<td>${esc(u.username)}</td><td>${esc(u.display_name)}</td>
                    <td>${roleName}</td><td class="text-muted">${esc(u.created_at)}</td>
                    <td class="text-center" style="white-space:nowrap;">
                        <button type="button" class="btn btn-sm btn-outline-secondary py-0 px-1" onclick="resetUserPw('${jsq(u.username)}')">重置密码</button>
                        <button type="button" class="btn btn-sm btn-outline-danger py-0 px-1" onclick="deleteUser('${jsq(u.username)}')">删除</button>
                    </td>`;
                body.appendChild(tr);
            });
        }

        async function resetUserPw(name) {
            const pwd = prompt('为 ' + name + ' 输入新密码（不少于6位）：');
            if (!pwd || pwd.length < 6) { showToast('密码不少于6位', 'warning'); return; }
            const res = await fetch('/api/users/' + encodeURIComponent(name) + '/password', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({password: pwd})
            });
            const data = await res.json();
            if (data.status === 'success') { showToast('密码已重置：' + name, 'success'); }
            else { showToast(data.message || '重置失败', 'danger'); }
        }

        async function deleteUser(name) {
            if (!confirm('确定删除用户 ' + name + '？')) return;
            const res = await fetch('/api/users/' + encodeURIComponent(name), {method: 'DELETE'});
            const data = await res.json();
            if (data.status === 'success') { showToast('已删除用户：' + name, 'success'); loadUsers(); }
            else { showToast(data.message || '删除失败', 'danger'); }
        }

        async function saveUser() {
            const username = document.getElementById('uName').value.trim();
            const display_name = document.getElementById('uDisplay').value.trim();
            const role = document.getElementById('uRole').value;
            const password = document.getElementById('uPwd').value;
            if (!username) { showToast('用户名不能为空', 'danger'); return; }
            const res = await fetch('/api/users', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({username: username, display_name: display_name, role: role, password: password})
            });
            const data = await res.json();
            if (data.status === 'success') {
                showToast('已创建用户：' + username, 'success');
                const m = bootstrap.Modal.getInstance(document.getElementById('userModal'));
                if (m) m.hide();
                document.getElementById('uName').value = '';
                document.getElementById('uDisplay').value = '';
                document.getElementById('uPwd').value = '';
                loadUsers();
            } else {
                showToast(data.message || '创建失败', 'danger');
            }
        }

        /* ================= 备份与恢复 ================= */
        async function downloadBackup() {
            try {
                const res = await fetch('/api/backup', {method: 'POST'});
                if (!res.ok) { showToast('备份失败', 'danger'); return; }
                const blob = await res.blob();
                const a = document.createElement('a');
                a.href = URL.createObjectURL(blob);
                a.download = '积分系统备份.zip';
                document.body.appendChild(a);
                a.click();
                a.remove();
                URL.revokeObjectURL(a.href);
                showToast('备份包已生成', 'success');
            } catch (e) {
                showToast('备份失败：' + e.message, 'danger');
            }
        }

        async function restoreBackup() {
            const file = document.getElementById('restoreFile').files[0];
            if (!file) { showToast('请先选择备份文件', 'warning'); return; }
            if (!confirm('恢复将覆盖现有历史周期、调权与计算结果数据（恢复前自动备份当前数据）。确定继续？')) return;
            const fd = new FormData();
            fd.append('backup_file', file);
            const res = await fetch('/api/restore', {method: 'POST', body: fd});
            const data = await res.json();
            if (data.status === 'success') {
                showToast('数据恢复成功', 'success');
                setTimeout(() => location.reload(), 800);
            } else {
                showToast(data.message || '恢复失败', 'danger');
            }
        }