</button>
                    </div>
                </div>
            </div>
        </div>     </div>     <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>

    <script>
        document.addEventListener('DOMContentLoaded', () => {
            loadStats();
            loadReports();
        });

        function showToast(message, isSuccess = true) {
            const resultDiv = document.getElementById('importResult');
            resultDiv.innerHTML = `<div class="alert alert-${isSuccess ? 'success' : 'danger'} alert-dismissible fade show" role="alert">
                <strong>${isSuccess ? 'Thành công' : 'Lỗi'}!</strong> ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
            </div>`;
        }

        // --- 1. IMPORT DATA ---
        async function importData() {
            const fileInput = document.getElementById('fileInput');
            const file = fileInput.files[0];
            if (!file) {
                showToast('Vui lòng chọn file Excel để import.', false);
                return;
            }

            const formData = new FormData();
            formData.append('file', file);

            try {
                const response = await axios.post('/api/import', formData, {
                    headers: { 'Content-Type': 'multipart/form-data' }
                });
                showToast(
                    `${response.data.message}. Tổng dòng hiện tại: ${response.data.total_rows}`,
                    true
                );
                loadStats(); // Cập nhật thống kê sau khi import
            } catch (error) {
                const msg = error.response?.data?.detail || error.message;
                showToast(`Lỗi import: ${msg}`, false);
            }
        }

        // --- 2. LOAD STATS & ORDERS ---
        async function loadStats() {
            try {
                const response = await axios.get('/api/orders');
                document.getElementById('totalOrders').textContent = response.data.orders.length;
                document.getElementById('totalRows').textContent = response.data.total_rows;
                populateOrderSelect(response.data.orders);
            } catch (error) {
                console.error('Lỗi tải thống kê:', error);
                document.getElementById('totalOrders').textContent = 'Lỗi';
                document.getElementById('totalRows').textContent = 'Lỗi';
            }
        }

        function populateOrderSelect(orders) {
            const select = document.getElementById('orderSelect');
            select.innerHTML = '<option value="">-- Chọn đơn hàng --</option>';
            orders.forEach(order => {
                select.innerHTML += `<option value="${order}">${order}</option>`;
            });
        }

        // --- 3. LOAD ORDER DETAIL ---
        async function loadOrderDetail() {
            const orderNo = document.getElementById('orderSelect').value;
            const detailDiv = document.getElementById('orderDetail');
            detailDiv.innerHTML = '';
            if (!orderNo) return;

            detailDiv.innerHTML = `<p class="text-center text-muted"><i class="fas fa-spinner fa-spin me-2"></i>Đang tải chi tiết...</p>`;

            try {
                const response = await axios.get(`/api/order/${orderNo}`);
                const data = response.data.data;

                let uniqueMaHang = [...new Set(data.map(item => item['MÃ HÀNG']))];
                
                detailDiv.innerHTML = `
                    <div class="alert alert-info mt-3">
                        <i class="fas fa-info-circle me-2"></i>
                        Đơn hàng <strong>${orderNo}</strong> có <strong>${data.length}</strong> dòng dữ liệu,
                        bao gồm <strong>${uniqueMaHang.length}</strong> Mã Hàng khác nhau.
                    </div>`;
            } catch (error) {
                const msg = error.response?.data?.detail || error.message;
                detailDiv.innerHTML = `<div class="alert alert-warning mt-3">Lỗi tải chi tiết: ${msg}</div>`;
            }
        }

        // --- 4. EXPORT REPORT ---
        async function exportWithTemplate() {
            const orderNo = document.getElementById('orderSelect').value;
            if (!orderNo) {
                showToast('Vui lòng chọn Đơn hàng để xuất báo cáo.', false);
                return;
            }
            
            // Hiển thị trạng thái đang xử lý
            const detailDiv = document.getElementById('orderDetail');
            detailDiv.innerHTML = `<p class="text-center text-primary mt-3"><i class="fas fa-spinner fa-spin me-2"></i>Đang tạo báo cáo, vui lòng chờ...</p>`;


            try {
                const response = await axios.post(`/api/export-template/${orderNo}`);
                const result = response.data;
                
                showToast(result.message, true);
                
                // Tự động tải xuống file
                window.location.href = result.download_url;

                loadReports(); // Cập nhật danh sách báo cáo
                loadOrderDetail(); // Tải lại chi tiết để xóa thông báo loading
            } catch (error) {
                const msg = error.response?.data?.detail || error.message;
                showToast(`Lỗi xuất báo cáo: ${msg}`, false);
            }
        }

        // --- 5. LOAD REPORTS LIST ---
        function formatBytes(bytes, decimals = 2) {
            if (bytes === 0) return '0 Bytes';
            const k = 1024;
            const dm = decimals < 0 ? 0 : decimals;
            const sizes = ['Bytes', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
        }

        async function loadReports() {
            const listBody = document.getElementById('reportsList');
            const countElement = document.getElementById('reportsCount');
            
            listBody.innerHTML = `<tr><td colspan="5" class="text-center text-muted py-4"><i class="fas fa-spinner fa-spin me-2"></i>Đang tải...</td></tr>`;
            countElement.textContent = "Đang tải...";

            try {
                const response = await axios.get('/api/reports');
                const reports = response.data.reports;
                
                listBody.innerHTML = '';
                
                if (reports.length === 0) {
                    listBody.innerHTML = `<tr><td colspan="5" class="text-center text-muted py-4">Chưa có báo cáo nào được tạo.</td></tr>`;
                } else {
                    reports.forEach(report => {
                        listBody.innerHTML += `
                            <tr class="report-item">
                                <td>${report.filename}</td>
                                <td><span class="badge bg-primary">${report.order_no}</span></td>
                                <td>${formatBytes(report.file_size)}</td>
                                <td>${report.created_time}</td>
                                <td class="action-buttons">
                                    <a href="/api/download/${report.filename}" class="btn btn-sm btn-success me-2" title="Tải xuống">
                                        <i class="fas fa-download"></i>
                                    </a>
                                    <button class="btn btn-sm btn-danger" onclick="deleteReport('${report.filename}')" title="Xóa">
                                        <i class="fas fa-trash"></i>
                                    </button>
                                </td>
                            </tr>
                        `;
                }
                
                countElement.textContent = `Tổng cộng: ${reports.length} báo cáo`;
            } catch (error) {
                console.error('Lỗi tải danh sách báo cáo:', error);
                listBody.innerHTML = `<tr><td colspan="5" class="text-center text-danger py-4">Lỗi: Không thể tải danh sách báo cáo.</td></tr>`;
                countElement.textContent = "Lỗi tải!";
            }
        }

        // --- 6. DELETE REPORTS ---
        async function deleteReport(filename) {
            if (!confirm(`Bạn có chắc chắn muốn xóa báo cáo ${filename} không?`)) return;
            
            try {
                await axios.delete(`/api/reports/${filename}`);
                showToast(`Đã xóa báo cáo ${filename} thành công.`, true);
                loadReports();
            } catch (error) {
                const msg = error.response?.data?.detail || error.message;
                showToast(`Lỗi xóa báo cáo: ${msg}`, false);
            }
        }

        async function clearAllReports() {
            if (!confirm('Bạn có chắc chắn muốn xóa TẤT CẢ báo cáo đã tạo không? Thao tác này không thể hoàn tác!')) return;
            
            try {
                const response = await axios.delete('/api/reports');
                showToast(response.data.message, true);
                loadReports();
            } catch (error) {
                const msg = error.response?.data?.detail || error.message;
                showToast(`Lỗi xóa tất cả báo cáo: ${msg}`, false);
            }
        }
        
        // --- 7. TEMPLATE MANAGEMENT ---
        async function uploadTemplate(endpoint, fileId, successMessage) {
            const fileInput = document.getElementById(fileId);
            const file = fileInput.files[0];
            if (!file) {
                alert('Vui lòng chọn file.');
                return;
            }

            const formData = new FormData();
            formData.append('file', file);

            try {
                const response = await axios.post(endpoint, formData, {
                    headers: { 'Content-Type': 'multipart/form-data' }
                });
                alert(response.data.message);
            } catch (error) {
                const msg = error.response?.data?.detail || error.message;
                alert(`Lỗi tải lên: ${msg}`);
            }
        }
    </script>

</body>
</html>
"""
