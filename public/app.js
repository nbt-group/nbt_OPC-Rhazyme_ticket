const supabase = window.supabase.createClient('YOUR_SUPABASE_URL', 'YOUR_ANON_KEY');

async function loadTickets() {
    const { data, error } = await supabase.from('emulsion_tickets').select('*');
    if (error) return console.error(error);
    
    const container = document.getElementById('tickets-container');
    container.innerHTML = data.map(t => `
        <div class="ticket-card">
            <h3>${t.issue_key}: ${t.summary}</h3>
            <p><strong>Status:</strong> ${t.status} | <strong>Customer:</strong> ${t.customer || '-'} | <strong>Dest:</strong> ${t.destination || '-'}</p>
            <ul>
                ${t.item_1 ? `<li>${t.item_1}: <strong>${t.qty_1}</strong></li>` : ''}
                ${t.item_2 ? `<li>${t.item_2}: <strong>${t.qty_2}</strong></li>` : ''}
                ${t.item_3 ? `<li>${t.item_3}: <strong>${t.qty_3}</strong></li>` : ''}
            </ul>
            <div class="links" style="margin-top: 10px;">
                ${t.po_link ? `<a href="${t.po_link}" target="_blank">📄 PO Link</a>` : ''}
                ${t.do_link ? `<a href="${t.do_link}" target="_blank">📄 DO Link</a>` : ''}
                ${t.invoice_link ? `<a href="${t.invoice_link}" target="_blank">📄 Invoice</a>` : ''}
                ${t.bc_bl_link ? `<a href="${t.bc_bl_link}" target="_blank">🚢 Vessel BC/BL</a>` : ''}
            </div>
            <div style="margin-top: 15px; padding-top: 10px; border-top: 1px solid #eee; font-size: 13px;">
                <strong>Latest Update:</strong><br>
                ${t.latest_comment}
            </div>
        </div>
    `).join('');
}
document.addEventListener('DOMContentLoaded', loadTickets);