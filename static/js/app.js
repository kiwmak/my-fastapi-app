const API_BASE = '/api';

// Hiển thị section
function showSection(sectionName) {
    document.querySelectorAll('[id$="-section"]').forEach(section => {
        section.style.display = 'none';
    });
    document.getElementById(sectionName + '-section').style.display = 'block';
    
    // Load dữ liệu cho section
    switch(sectionName) {
        case 'dashboard':
            loadDashboard();
            break;
        case 'orders':
            loadOrders();
            break;
        case 'reports':
            loadExportOrders();
            break;
    }
}

// Load dashboard
async function loadDashboard() {
    try {
        const [ordersResponse, chartResponse] = await Promise.all([
            axios.get(`${API_BASE}/orders`),
            axios.get(`${API_BASE}/chart`)
        ]);

        const orders = ordersResponse.data.orders || [];
        const chartData = chartResponse.data.chart_data || {};

        // Update stats
        document.getElementById('total-orders').textContent = orders.length;
        document.getElementById('total-customers').textContent = chartData.customers ? chartData.customers.length : 0;
        
        // Load additional stats
        const detailResponse = await axios.get(`${API_BASE}/order/${orders[0]}`);
        if (detailResponse.data.data) {
            const products = new Set(detailResponse.data.data.map(item => item['MÃ HÀNG']));
            document.getElementById('total-products').textContent = products.size;
            document.getElementById('total-rows').textContent = detailResponse.data.data.length;
        }

        // Render chart
        if (chartData.customers && chartData.customers.length > 0) {
            renderChart(chartData.customers, chartData.order_counts);
        } else {
            document.getElementById('chart-container').innerHTML = 
                '<p class="text-muted text-center">Không có dữ liệu để hiển thị biểu đồ</p>';
        }

    } catch (error) {
        console.error('Lỗi load dashboard:', error);
        showAlert('Có lỗi xảy ra khi tải dashboard', 'danger');
    }
}

// Render biểu đồ
function renderChart(customers, counts) {
    const trace = {
        x: customers,
        y: counts,
        type: 'bar',
        marker: {
            color: ['#3498db', '#2ecc71', '#e74c3c', '#f39c12', '#9b59b6']
        }
    };

    const layout = {
        title: 'TOP 5 KHÁCH HÀNG CÓ NHIỀU ĐƠN NHẤT',
        xaxis: { title: 'Khách hàng' },
        yaxis: { title: 'Số đơn hàng' },
        plot_bgcolor: '#f8f9fa',
        paper_bgcolor: '#f8f9fa'
    };

    Plotly.newPlot('chart-container', [trace], layout);
}

// Import dữ liệu
async function importData() {
    const fileInput = document.getElementById('fileInput');
    const file = fileInput.files[0];
    
    if (!file) {
        showAlert('Vui lòng chọn file Excel', 'warning');
        return;
    }

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await axios.post(`${API_BASE}/import`, formData, {
            headers: { 'Content-Type': 'multipart/form-data' }
        });

        const result = response.data;
        if (result.success) {
            showAlert(`✅ ${result.message}`, 'success');
            fileInput.value = '';
            loadDashboard(); // Refresh data
        } else {
            showAlert(`❌ ${result.message}`, 'danger');
        }
    } catch (error) {
        console.error('Lỗi import:', error);
        showAlert('Có lỗi xảy ra khi import dữ liệu', 'danger');
    }
}

// Load danh sách đơn hàng
async function loadOrders() {
    try {
        const response = await axios.get(`${API_BASE}/orders`);
        const orders = response.data.orders || [];
        
        const select = document.getElementById('orderSelect');
        select.innerHTML = '<option value="">-- Chọn đơn hàng --</option>';
        
        orders.forEach(order => {
            const option = document.createElement('option');
            option.value = order;
            option.textContent = order;
            select.appendChild(option);
        });
    } catch (error) {
        console.error('Lỗi load orders:', error);
        showAlert('Có lỗi xảy ra khi tải danh sách đơn hàng', 'danger');
    }
}

// Load chi tiết đơn hàng
async function loadOrderDetail() {
    const orderNo = document.getElementById('orderSelect').value;
    if (!orderNo) return;

    try {
        const response = await axios.get(`${API_BASE}/order/${orderNo}`);
        const orderData = response.data.data || [];
        
        const container = document.getElementById('order-detail');
        
        if (orderData.length === 0) {
            container.innerHTML = '<p class="text-muted">Không có dữ liệu cho đơn hàng này</p>';
            return;
        }

        let html = `
            <div class="d-flex justify-content-between align-items-center mb-3">
                <h5>Chi tiết đơn hàng: ${orderNo}</h5>
                <div>
                    <button class="btn btn-danger btn-sm" onclick="deleteOrder('${orderNo}')">
                        <i class="fas fa-trash"></i> Xóa đơn hàng
                    </button>
                </div>
            </div>
            <div class="table-responsive">
                <table class="table table-striped">
                    <thead>
                        <tr>
                            ${Object.keys(orderData[0]).map(key => `<th>${key}</th>`).join('')}
                        </tr>
                    </thead>
                    <tbody>
                        ${orderData.map(row => `
                            <tr>
                                ${Object.values(row).map(value => `<td>${value || ''}</td>`).join('')}
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        `;
        
        container.innerHTML = html;
    } catch (error) {
        console.error('Lỗi load order detail:', error);
        showAlert('Có lỗi xảy ra khi tải chi tiết đơn hàng', 'danger');
    }
}

// Xóa đơn hàng
async function deleteOrder(orderNo) {
    if (!confirm(`Bạn có chắc muốn xóa đơn hàng "${orderNo}"?`)) return;

    try {
        const response = await axios.delete(`${API_BASE}/order/${orderNo}`);
        
        if (response.data.success) {
            showAlert('✅ Đã xóa đơn hàng thành công', 'success');
            loadOrders();
            document.getElementById('order-detail').innerHTML = '';
            loadDashboard(); // Refresh stats
        } else {
            showAlert(`❌ ${response.data.message}`, 'danger');
        }
    } catch (error) {
        console.error('Lỗi xóa order:', error);
        showAlert('Có lỗi xảy ra khi xóa đơn hàng', 'danger');
    }
}

// Load orders cho export
async function loadExportOrders() {
    try {
        const response = await axios.get(`${API_BASE}/orders`);
        const orders = response.data.orders || [];
        
        const select = document.getElementById('exportOrderSelect');
        select.innerHTML = '<option value="">-- Chọn đơn hàng --</option>';
        
        orders.forEach(order => {
            const option = document.createElement('option');
            option.value = order;
            option.textContent = order;
            select.appendChild(option);
        });
    } catch (error) {
        console.error('Lỗi load export orders:', error);
    }
}

// Export báo cáo
async function exportReport() {
    const orderNo = document.getElementById('exportOrderSelect').value;
    if (!orderNo) {
        showAlert('Vui lòng chọn đơn hàng', 'warning');
        return;
    }

    try {
        const response = await axios.post(`${API_BASE}/export/${orderNo}`);
        const result = response.data;
        
        if (result.success) {
            showAlert(`✅ ${result.message}`, 'success');
            // Tạo link download
            const downloadLink = document.createElement('a');
            downloadLink.href = result.file_url;
            downloadLink.download = '';
            downloadLink.style.display = 'none';
            document.body.appendChild(downloadLink);
            downloadLink.click();
            document.body.removeChild(downloadLink);
        } else {
            showAlert(`❌ ${result.message}`, 'danger');
        }
    } catch (error) {
        console.error('Lỗi export:', error);
        showAlert('Có lỗi xảy ra khi xuất báo cáo', 'danger');
    }
}

// Hiển thị thông báo
function showAlert(message, type) {
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type} alert-dismissible fade show`;
    alertDiv.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    
    // Tìm container phù hợp
    let container = document.getElementById('import-result') || 
                   document.getElementById('export-result') || 
                   document.getElementById('order-detail') ||
                   document.querySelector('.main-content');
    
    container.appendChild(alertDiv);
    
    // Tự động xóa sau 5s
    setTimeout(() => {
        if (alertDiv.parentNode) {
            alertDiv.parentNode.removeChild(alertDiv);
        }
    }, 5000);
}

// Refresh data
function refreshData() {
    loadDashboard();
    showAlert('Đã làm mới dữ liệu', 'info');
}

// Khởi tạo khi load trang
document.addEventListener('DOMContentLoaded', function() {
    loadDashboard();
    loadOrders();
    loadExportOrders();
});